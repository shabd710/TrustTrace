/*
 * TrustTraceAccessibilityService.kt -- whitelisted-package,
 * non-recursive-traversal AccessibilityService for transaction-time
 * intervention.
 *
 * Spec ref: PDF Section 2.3, 7.4 ("an AccessibilityService that can
 * inspect anything is close to the exact capability this app's own
 * stalkerware scanner looks for; scoping inspection to a verified
 * payment-app whitelist by construction is what keeps this module on the
 * right side of that line"), 9.2 (Kotlin coroutine-based non-recursive
 * traversal), 8.3 (accessibility-tree scanning restricted to actionable
 * nodes within the whitelisted payment-app paths, event
 * rate-limiting/debouncing), 10.2 (tapjacking fix via
 * setFilterTouchesWhenObscured(true) on the override button).
 *
 * NOT COMPILED/RUN HERE -- needs the Android SDK + a real device/emulator
 * with the service granted under Play Store's scam/fraud-prevention
 * accessibility-use category. Written to the real AccessibilityService
 * API surface.
 */
package com.trusttrace.native_modules.android

import android.accessibilityservice.AccessibilityService
import android.view.accessibility.AccessibilityEvent
import android.view.accessibility.AccessibilityNodeInfo
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.launch
import java.util.ArrayDeque

/**
 * Hardcoded whitelist of regional banking/payment/crypto-exchange package
 * identifiers. ANY package not on this list is ignored before any tree
 * walk begins -- this is the structural enforcement of spec 7.4's
 * "scoping inspection to a verified payment-app whitelist BY
 * CONSTRUCTION", not a runtime check that could be bypassed by a bug
 * elsewhere.
 */
private val PAYMENT_APP_WHITELIST: Set<String> = setOf(
    "com.google.android.apps.nbu.paisa.user",  // Google Pay (India/UPI)
    "net.one97.paytm",                          // Paytm
    "com.phonepe.app",                          // PhonePe
    "com.chase.sig.android",                    // Chase
    "com.infonow.bofa",                         // Bank of America
    "com.coinbase.android",                     // Coinbase
    // Production: full regional list maintained + versioned separately,
    // reviewed whenever a new high-volume regional payment app is added
    // (spec 9.2's UPI-intent-interception template extends to PIX/PromptPay
    // equivalents the same way).
)

private const val EVENT_DEBOUNCE_MS = 250L  // spec 8.3: rate-limit/debounce duplicate accessibility events

class TrustTraceAccessibilityService : AccessibilityService() {

    private val scope = CoroutineScope(Dispatchers.Default)
    private var lastEventTimestampMs = 0L

    override fun onAccessibilityEvent(event: AccessibilityEvent?) {
        val pkg = event?.packageName?.toString() ?: return

        // Whitelist gate FIRST, before any other work -- see class doc.
        if (pkg !in PAYMENT_APP_WHITELIST) return

        val now = System.currentTimeMillis()
        if (now - lastEventTimestampMs < EVENT_DEBOUNCE_MS) return  // spec 8.3 debounce
        lastEventTimestampMs = now

        val root = rootInActiveWindow ?: return
        scope.launch {
            val actionableNodes = traverseActionableNodesNonRecursive(root)
            evaluateTransactionScreen(pkg, actionableNodes)
        }
    }

    /**
     * Explicit iterative stack-based traversal -- spec 9.2's "Kotlin
     * coroutine-based (non-recursive) accessibility-tree traversal".
     * Recursion on a deep/malformed node tree risks a stack overflow;
     * an explicit stack has no such recursion-depth ceiling. Restricted
     * to ACTIONABLE nodes only within the already-whitelisted app's tree
     * (spec 8.3), not a full unrestricted dump of every node.
     */
    private fun traverseActionableNodesNonRecursive(root: AccessibilityNodeInfo): List<AccessibilityNodeInfo> {
        val actionable = mutableListOf<AccessibilityNodeInfo>()
        val stack = ArrayDeque<AccessibilityNodeInfo>()
        stack.push(root)

        while (stack.isNotEmpty()) {
            val node = stack.pop()
            if (node.isClickable || node.isEditable || node.isCheckable) {
                actionable.add(node)
            }
            for (i in 0 until node.childCount) {
                node.getChild(i)?.let { stack.push(it) }
            }
        }
        return actionable
    }

    private fun evaluateTransactionScreen(packageName: String, nodes: List<AccessibilityNodeInfo>) {
        // Hands off to detection/transaction/risk_scorer.py's logic via
        // the mobile app's cross-layer bridge (JS/JSI) -- this function's
        // job ends at "here is the actionable-node text from a
        // whitelisted payment app", never at deciding to block/cancel
        // anything itself. Hard rule (Strict Instruction Summary):
        // this service has NO code path that can cancel, delay, or
        // reverse a transaction -- only surface a warning overlay via
        // the mobile app's UI layer.
        val extractedTexts = nodes.mapNotNull { it.text?.toString() }
        // -> bridged to JS: TrustTraceBridge.onPaymentScreenText(packageName, extractedTexts)
    }

    override fun onInterrupt() { /* required override, no-op */ }
}

/*
 * Tapjacking fix for the "I understand, continue anyway" override button
 * (spec 10.2): applied at the View level in the warning-overlay Activity,
 * not in this service class (the service only detects/surfaces; the
 * override button lives in the mobile app's own UI layer). Documented
 * here since this file is this override's originating security context:
 *
 *   overrideButton.filterTouchesWhenObscured = true
 *
 * setFilterTouchesWhenObscured(true) is a real Android View API built
 * specifically to reject touches when another window is detected
 * overlaying the view -- applied as a hard requirement, not optional
 * hardening, per spec 10.2.
 */
