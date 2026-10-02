package io.htu.toolbox

import android.content.Context
import android.security.keystore.KeyGenParameterSpec
import android.security.keystore.KeyProperties
import android.util.Base64
import org.json.JSONObject
import java.security.KeyStore
import javax.crypto.Cipher
import javax.crypto.KeyGenerator
import javax.crypto.SecretKey
import javax.crypto.spec.GCMParameterSpec
import kotlin.concurrent.withLock

data class Account(val id: String, val operator: String, val portal: String, val interval: Int, val autoStart: Boolean)

class Credentials(context: Context) {
    private val prefs = context.getSharedPreferences("htu-connect", Context.MODE_PRIVATE)
    fun configured(): Boolean = prefs.contains("password")
    fun account(): Account = Account(prefs.getString("account", "")!!, prefs.getString("operator", "lt")!!,
        prefs.getString("portal", "")!!, prefs.getInt("interval", 10), prefs.getBoolean("autoStart", false))
    private fun key(): SecretKey {
        val store = KeyStore.getInstance("AndroidKeyStore").apply { load(null) }
        val existing = store.getKey("htu-connect-password", null)
        if (existing is SecretKey) return existing
        val generator = KeyGenerator.getInstance(KeyProperties.KEY_ALGORITHM_AES, "AndroidKeyStore")
        generator.init(KeyGenParameterSpec.Builder("htu-connect-password", KeyProperties.PURPOSE_ENCRYPT or KeyProperties.PURPOSE_DECRYPT)
            .setBlockModes(KeyProperties.BLOCK_MODE_GCM).setEncryptionPaddings(KeyProperties.ENCRYPTION_PADDING_NONE).build())
        return generator.generateKey()
    }
    fun password(): String {
        try {
            val payload = JSONObject(prefs.getString("password", "")!!)
            val cipher = Cipher.getInstance("AES/GCM/NoPadding")
            cipher.init(Cipher.DECRYPT_MODE, key(), GCMParameterSpec(128, Base64.decode(payload.getString("iv"), Base64.NO_WRAP)))
            return String(cipher.doFinal(Base64.decode(payload.getString("data"), Base64.NO_WRAP)), Charsets.UTF_8)
        } catch (_: Exception) { throw IllegalStateException("密码无法解密，请在本机重新保存密码") }
    }
    fun save(account: Account, password: String) {
        Operations.lock.withLock { saveLocked(account, password) }
    }
    private fun saveLocked(account: Account, password: String) {
        require(account.id.matches(Regex("[A-Za-z0-9._-]{1,64}"))) { "账号格式无效" }
        require(account.operator in listOf("yd", "lt", "dx", "hsd")) { "运营商无效" }
        PortalPolicy.validate(account.portal)
        require(account.interval in 5..3600) { "检测间隔须为 5 到 3600 秒" }
        require(password.isEmpty() || (password.isNotBlank() && password.length <= 128)) { "密码格式无效" }
        require(password.isNotEmpty() || configured()) { "首次配置必须输入上网密码" }
        val edit = prefs.edit().putString("account", account.id).putString("operator", account.operator)
            .putString("portal", account.portal).putInt("interval", account.interval).putBoolean("autoStart", account.autoStart)
        if (password.isNotEmpty()) {
            val cipher = Cipher.getInstance("AES/GCM/NoPadding"); cipher.init(Cipher.ENCRYPT_MODE, key())
            val value = JSONObject().put("iv", Base64.encodeToString(cipher.iv, Base64.NO_WRAP))
                .put("data", Base64.encodeToString(cipher.doFinal(password.toByteArray(Charsets.UTF_8)), Base64.NO_WRAP))
            edit.putString("password", value.toString())
        }
        check(edit.commit()) { "配置保存失败" }
    }
    fun enabled(): Boolean = prefs.getBoolean("enabled", false)
    fun enable(value: Boolean) { check(prefs.edit().putBoolean("enabled", value).commit()) }
}
