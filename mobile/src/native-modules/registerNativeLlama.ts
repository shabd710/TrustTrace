/**
 * REAL native Llama runtime binding (llama.cpp via `llama.rn`).
 *
 * Spec ref: PDF Target Environment ("a mature, already-optimized mobile LLM
 * runtime -- llama.cpp (Metal/Vulkan backend), MLC-LLM, Apple MLX, or
 * Google's MediaPipe LLM Inference"), Section 3.4 (mature runtime owns
 * quantization / GQA / speculative decoding), Section 5 (on-device-first).
 *
 * ---------------------------------------------------------------------------
 * WHY THIS FILE IS EXCLUDED FROM THE SANDBOX TYPECHECK (tsconfig `exclude`):
 * it imports `llama.rn`, a native package that ships prebuilt llama.cpp `.so`
 * / `.a` binaries and a TurboModule. That package is only present in a real
 * device build (`npm install llama.rn` + `expo prebuild` + gradle). In this
 * repo's verification sandbox it is not installed, so this file is compiled
 * ONLY in a real build. All engine-agnostic logic it depends on
 * (prompting, JSON grounding, blending) lives in the typechecked+tested
 * src/ml/nativeLlamaScorer.ts.
 * ---------------------------------------------------------------------------
 *
 * Flow (matches the milestone diagram):
 *   startup -> registerNativeLlamaScorerIfAvailable()
 *           -> initLlama(Tier-1 GGUF)             [llama.cpp loads weights]
 *           -> createNativeLlamaScorer(engine)   [engine-agnostic glue]
 *           -> registerEdgeRuntime(scorer)       [supersedes default TS scorer]
 *   thereafter: scoreTranscript -> native scorer -> llama.cpp completion
 *               -> blend with heuristic cascade -> PasteCheckResult
 *
 * The Tier-2 (3B) model + cross-tier speculative decoding are exposed via the
 * EdgeRuntimeBinding for the high-stakes escalation path; the per-message
 * default blend uses Tier-1 only, because Tier 2 must never be the default
 * path (spec 3.1).
 *
 * MODEL LIFECYCLE (memory safety): GGUF contexts are large (a 1B f16 ~2.5 GB;
 * a 3B ~3.5 GB). To avoid OOM background-kills, this module ties residency to
 * app lifecycle via AppState:
 *   - on background/inactive  -> release the Tier-2 escalation context (Tier-1
 *                                stays so the default path resumes instantly);
 *   - on memoryWarning        -> release BOTH contexts and restore the pure-TS
 *                                on-device scorer (ensureOnDeviceScorer), so
 *                                scoring stays ON-DEVICE (never the network)
 *                                while unloaded;
 *   - on returning to active  -> reload Tier-1 and re-register the blended
 *                                scorer.
 * Releases are skipped while a completion is in flight (releasing a live
 * context can crash the native layer).
 */
// eslint-disable-next-line import/no-unresolved -- present only in device builds
import { initLlama, type LlamaContext } from "llama.rn";
import { AppState, type AppStateStatus } from "react-native";

import {
  registerEdgeRuntime,
  EdgeRuntimeBinding,
  ModelLoadResult,
  CascadeTier,
} from "../ml/modelLoader";
import { createNativeLlamaScorer, LlamaEngine } from "../ml/nativeLlamaScorer";
import { ensureOnDeviceScorer } from "../ml/defaultScorer";
import {
  resolveExistingTier1ModelPath,
  resolveExistingTier2ModelPath,
  tier1CandidatePaths,
  diagnoseModelProvisioning,
} from "./modelProvisioning";

// Tagged logs so the model bring-up is observable in Metro / `adb logcat`.
const TAG = "[TrustTrace/native-llama]";
function log(...args: unknown[]): void {
  // eslint-disable-next-line no-console
  console.log(TAG, ...args);
}

// llama.cpp init params tuned for a phone: small context (the grounding prompt
// is short), single sequence. GPU offload is decided adaptively at init time
// (see initLlamaAdaptive) rather than hardcoded, because full-offload support
// varies across Android GPUs/drivers and an unsupported value can fail init.
const TIER1_BASE = { n_ctx: 2048, n_batch: 512 } as const;
const TIER2_BASE = { n_ctx: 4096, n_batch: 512 } as const;

// Stop at the Llama-3 turn terminator so we don't run past the JSON.
const STOP = ["<|eot_id|>", "<|end_of_text|>"];

/**
 * Requested GPU offload layer count. Defaults to full offload (99) but is
 * overridable via env for devices where Vulkan/Metal offload misbehaves, e.g.
 * `EXPO_PUBLIC_TRUSTTRACE_N_GPU_LAYERS=0` forces CPU. Adaptive init falls back
 * to CPU automatically if the requested GPU offload fails.
 */
function requestedGpuLayers(): number {
  const raw = process.env.EXPO_PUBLIC_TRUSTTRACE_N_GPU_LAYERS;
  const n = raw != null ? Number(raw) : NaN;
  return Number.isFinite(n) && n >= 0 ? n : 99;
}

/** initLlama with adaptive GPU offload: try GPU, fall back to CPU on failure. */
async function initLlamaAdaptive(
  modelPath: string,
  base: { n_ctx: number; n_batch: number },
  label: string,
): Promise<LlamaContext> {
  const gpu = requestedGpuLayers();
  try {
    return await initLlama({ model: modelPath, ...base, n_gpu_layers: gpu });
  } catch (err) {
    if (gpu > 0) {
      log(
        `${label}: GPU offload (n_gpu_layers=${gpu}) failed, retrying on CPU (n_gpu_layers=0):`,
        String(err),
      );
      return await initLlama({ model: modelPath, ...base, n_gpu_layers: 0 });
    }
    throw err;
  }
}

/** Derive an honest model id from the actual GGUF filename (no q4/f16 guess). */
function modelIdFromPath(p: string): string {
  const base = p.split("/").pop() ?? p;
  return base.replace(/\.gguf$/i, "");
}

/** LlamaEngine backed by an already-resident llama.rn Tier-1 context. */
class LlamaRnEngine implements LlamaEngine {
  private ctx: LlamaContext | null;
  private busy = false;
  constructor(private readonly id: string, ctx: LlamaContext) {
    this.ctx = ctx;
  }

  isReady(): boolean {
    return this.ctx !== null;
  }

  isBusy(): boolean {
    return this.busy;
  }

  modelId(): string {
    return this.id;
  }

  async complete(prompt: string, opts?: { maxTokens?: number }): Promise<string> {
    const ctx = this.ctx;
    if (ctx === null) {
      throw new Error("Tier-1 context has been released");
    }
    this.busy = true;
    try {
      const res = await ctx.completion({
        prompt,
        n_predict: opts?.maxTokens ?? 256,
        temperature: 0, // deterministic, grounded scoring (matches llm_runtime.py)
        stop: STOP,
      });
      return res.text ?? "";
    } finally {
      this.busy = false;
    }
  }

  /** Release the Tier-1 context. Safe to call repeatedly. */
  async release(): Promise<void> {
    const ctx = this.ctx;
    this.ctx = null;
    if (ctx !== null) {
      try {
        await ctx.release();
      } catch (err) {
        log("Tier-1 release error (ignored):", String(err));
      }
    }
  }
}

/**
 * EdgeRuntimeBinding over llama.rn: holds the resident Tier-1 draft model and
 * lazily loads Tier-2 for the speculative-decoding escalation path. The
 * runtime itself owns acceptance sampling / abort-on-divergence (spec 3.4);
 * this binding only exposes the high-level calls.
 */
class LlamaRnBinding implements EdgeRuntimeBinding {
  private tier2: LlamaContext | null = null;
  private tier2Busy = false;
  constructor(private readonly tier1: LlamaContext) {}

  async loadTier(tier: CascadeTier): Promise<ModelLoadResult> {
    if (tier === 2 && this.tier2 === null) {
      const tier2Path = await resolveExistingTier2ModelPath();
      if (tier2Path !== null) {
        this.tier2 = await initLlamaAdaptive(tier2Path, TIER2_BASE, "Tier-2");
      }
    }
    const resident = tier === 2 ? this.tier2 !== null : this.tier1 !== null;
    return {
      tier,
      modelId: tier === 2 ? "llama-3.2-3b" : "llama-3.2-1b",
      residentInMemory: resident,
    };
  }

  async runTier2WithSpeculativeDecoding(prompt: string): Promise<string> {
    await this.loadTier(2);
    if (this.tier2 === null) {
      throw new Error("Tier 2 model unavailable");
    }
    // llama.rn accepts the resident Tier-1 model as the speculative draft
    // context (spec 3.4). The field only exists on newer binding versions;
    // an `as` cast keeps this compiling on either -- older versions ignore
    // the extra key and fall back to standard single-model decoding.
    const params = {
      prompt,
      n_predict: 512,
      temperature: 0,
      stop: STOP,
      draft_context: this.tier1,
    } as Parameters<LlamaContext["completion"]>[0];
    this.tier2Busy = true;
    try {
      const res = await this.tier2.completion(params);
      return res.text ?? "";
    } finally {
      this.tier2Busy = false;
    }
  }

  isTier2Busy(): boolean {
    return this.tier2Busy;
  }

  /**
   * Release the Tier-2 context to free memory. Skipped if a Tier-2 completion
   * is in flight. Returns true if it released (or was already unloaded).
   */
  async releaseTier2(): Promise<boolean> {
    if (this.tier2Busy) {
      return false;
    }
    const ctx = this.tier2;
    this.tier2 = null;
    if (ctx !== null) {
      try {
        await ctx.release();
      } catch (err) {
        log("Tier-2 release error (ignored):", String(err));
      }
    }
    return true;
  }
}

// ---- Module state + lifecycle -------------------------------------------

let started = false;
let nativeBinding: LlamaRnBinding | null = null;
let engine: LlamaRnEngine | null = null;
let tier1ModelPath: string | null = null;
let needsReload = false;
let appStateWired = false;

/** The Tier-1/2 EdgeRuntimeBinding, once the native runtime has booted. */
export function getNativeBinding(): EdgeRuntimeBinding | null {
  return nativeBinding;
}

/** Bring up Tier-1 from a known path and register the blended scorer. */
async function bringUpTier1(modelPath: string): Promise<boolean> {
  try {
    log("loading Tier-1 model:", modelPath);
    const tier1Ctx = await initLlamaAdaptive(modelPath, TIER1_BASE, "Tier-1");
    const modelId = modelIdFromPath(modelPath);
    engine = new LlamaRnEngine(modelId, tier1Ctx);
    nativeBinding = new LlamaRnBinding(tier1Ctx);

    const scorer = createNativeLlamaScorer(engine, { maxTokens: 256 });
    // Register only AFTER the model is loaded, so isEdgeRuntimeAvailable()
    // (which gates on isReady()) never reports a not-yet-ready scorer.
    registerEdgeRuntime(scorer);
    log(`READY -- native model-blended scorer registered (model=${modelId}).`);
    return true;
  } catch (err) {
    log("init FAILED, staying on heuristic scorer:", String(err));
    engine = null;
    nativeBinding = null;
    return false;
  }
}

/** Release everything and restore the always-on TS scorer (stays on-device). */
async function releaseAllForMemory(): Promise<void> {
  if (engine !== null && engine.isBusy()) {
    return; // scoring in flight -- try again on the next signal
  }
  if (nativeBinding !== null) {
    await nativeBinding.releaseTier2();
  }
  if (engine !== null) {
    await engine.release();
  }
  engine = null;
  nativeBinding = null;
  needsReload = tier1ModelPath !== null;
  // Restore the pure-TS on-device scorer so scoring never routes to the
  // network while the model is unloaded (privacy). ensureOnDeviceScorer only
  // registers when no ready scorer is active, which is now the case.
  ensureOnDeviceScorer();
  log("released all contexts under memory pressure; TS scorer restored.");
}

function wireAppStateLifecycle(): void {
  if (appStateWired) {
    return;
  }
  appStateWired = true;

  AppState.addEventListener("change", (state: AppStateStatus) => {
    if (state === "background" || state === "inactive") {
      // Free the big escalation model when leaving the foreground; keep Tier-1
      // resident for instant resume.
      if (nativeBinding !== null) {
        void nativeBinding.releaseTier2();
      }
    } else if (state === "active" && needsReload && tier1ModelPath !== null) {
      needsReload = false;
      void bringUpTier1(tier1ModelPath);
    }
  });

  // iOS delivers low-memory as a dedicated event; Android low-memory arrives
  // via background transitions handled above. Release aggressively here.
  AppState.addEventListener("memoryWarning", () => {
    void releaseAllForMemory();
  });
}

/**
 * Bring up the native Tier-1 model and register the model-blended scorer.
 * Idempotent and side-effecting; never throws (callers fire-and-forget). If
 * llama.rn is missing or the weights are not provisioned, it simply returns
 * and the default TS Tier-0 scorer stays in place.
 */
export async function registerNativeLlamaScorerIfAvailable(): Promise<void> {
  if (started) {
    return;
  }
  started = true;

  // CRITICAL: only ever hand an EXISTING file to initLlama -- a native
  // model-load failure can abort the whole app (a crash JS try/catch cannot
  // catch). With no weights present we stay completely dormant, and the app
  // runs exactly like the tested heuristic-only build.
  const modelPath = await resolveExistingTier1ModelPath();
  if (modelPath === null) {
    log(
      "no Tier-1 GGUF found -- staying on the heuristic scorer. Looked in:",
      tier1CandidatePaths(),
    );
    // Dump what the app's OWN process can actually see (stat + dir listings),
    // so a false negative from expo's canRead() gate is visible in logcat
    // instead of being silently swallowed.
    await diagnoseModelProvisioning();
    started = false; // allow a retry after weights are provisioned
    return;
  }

  tier1ModelPath = modelPath;
  const ok = await bringUpTier1(modelPath);
  if (!ok) {
    started = false; // allow a retry
    tier1ModelPath = null;
    return;
  }
  wireAppStateLifecycle();
}
