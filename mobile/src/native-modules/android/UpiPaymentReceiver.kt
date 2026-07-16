/*
 * UpiPaymentReceiver.kt -- direct upi://pay intent interception.
 *
 * Spec ref: PDF Section 2.3 ("direct Android broadcast filters capturing
 * intent calls matching the 'upi://pay' payment rail to isolate
 * transaction tracking without text scanning overhead"), 9.2 ("a
 * genuinely high-value, region-specific addition -- India's real-time
 * payment rail, caught directly via intent filter rather than inferred
 * from generic accessibility-tree scanning ... worth treating as a
 * template: other high-volume regional real-time-payment schemes (PIX in
 * Brazil, PromptPay in Thailand) merit the same treatment").
 *
 * NOT COMPILED/RUN HERE -- see SecureBuffer.kt's note.
 */
package com.trusttrace.native_modules.android

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.net.Uri

class UpiPaymentReceiver : BroadcastReceiver() {

    override fun onReceive(context: Context, intent: Intent) {
        val data: Uri = intent.data ?: return
        if (data.scheme != "upi" || data.host != "pay") return

        // UPI deep-link query params: pa (payee address), am (amount),
        // pn (payee name), tn (transaction note). Real, standard UPI
        // intent spec fields -- direct, structured extraction, "without
        // text scanning overhead" per spec 2.3.
        val payeeAddress = data.getQueryParameter("pa")
        val amountStr = data.getQueryParameter("am")
        val payeeName = data.getQueryParameter("pn")

        val amount = amountStr?.toDoubleOrNull()
        if (payeeAddress != null && amount != null) {
            // -> bridged to JS: TrustTraceBridge.onUpiPaymentIntent(payeeAddress, amount, payeeName)
            // Feeds directly into detection/transaction/payee_novelty_check.py's
            // compound-risk logic -- same hard rule as
            // TrustTraceAccessibilityService: this receiver only observes
            // and forwards, it has no path to cancel or alter the intent
            // it's intercepting.
        }
    }

    companion object {
        /**
         * Intent filter registered in AndroidManifest.xml:
         *   <intent-filter>
         *     <action android:name="android.intent.action.VIEW" />
         *     <data android:scheme="upi" android:host="pay" />
         *   </intent-filter>
         * Template for other regional real-time-payment schemes per spec
         * 9.2 -- e.g. a PixPaymentReceiver would filter on scheme="pix",
         * a PromptPayPaymentReceiver on Thailand's equivalent deep-link
         * scheme, following this exact same structural pattern.
         */
        const val MANIFEST_NOTE = "See class doc for AndroidManifest.xml intent-filter registration."
    }
}
