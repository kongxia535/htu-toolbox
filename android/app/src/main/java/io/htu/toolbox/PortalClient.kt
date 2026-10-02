package io.htu.toolbox

import org.json.JSONObject
import java.net.HttpURLConnection
import java.net.URI
import java.net.URL
import java.net.URLDecoder
import java.net.URLEncoder
import java.net.Proxy

class PortalClient(private val context: android.content.Context) {
    data class Response(val code: Int, val body: String, val location: String)
    private val probes = listOf("http://www.msftconnecttest.com/connecttest.txt" to "Microsoft Connect Test",
        "http://connectivitycheck.gstatic.com/generate_204" to null)
    private fun get(url: String): Response {
        // Captive Wi-Fi may not be the default network when mobile data is active.
        val manager = context.getSystemService(android.net.ConnectivityManager::class.java)
        val wifi = manager.allNetworks.firstOrNull {
            manager.getNetworkCapabilities(it)?.hasTransport(android.net.NetworkCapabilities.TRANSPORT_WIFI) == true
        }
        val connection = (wifi?.openConnection(URL(url), Proxy.NO_PROXY) ?: URL(url).openConnection(Proxy.NO_PROXY)) as HttpURLConnection
        try {
            connection.connectTimeout = 3000; connection.readTimeout = 5000; connection.instanceFollowRedirects = false
            connection.setRequestProperty("User-Agent", "HTU-Connect/0.1")
            val status = connection.responseCode
            val input = if (status >= 400) connection.errorStream else connection.inputStream
            val bytes = input?.use { stream ->
                val output = java.io.ByteArrayOutputStream()
                val buffer = ByteArray(4096)
                while (true) {
                    val count = stream.read(buffer)
                    if (count < 0) break
                    output.write(buffer, 0, count)
                    check(output.size() <= 256 * 1024) { "响应过大" }
                }
                output.toByteArray()
            } ?: byteArrayOf()
            check(bytes.size <= 256 * 1024) { "响应过大" }
            return Response(status, String(bytes, Charsets.UTF_8), connection.getHeaderField("Location") ?: "")
        } catch (_: Exception) { throw IllegalStateException("网络请求失败或超时，请检查校园网络") }
        finally { connection.disconnect() }
    }
    fun online(): Boolean = probes.any { (url, expected) ->
        try { val response = get(url); PortalPolicy.online(response.code, response.body, expected) } catch (_: Exception) { false }
    }
    fun detect(): String {
        for ((url, _) in probes) {
            try {
                val response = get(url)
                val candidates = listOf(response.location) + Regex("https?://[^\\s\"'<>]+/portal\\.do\\?[^\\s\"'<>]+")
                    .findAll(response.body).map { it.value.replace("&amp;", "&") }.toList()
                for (candidate in candidates) try { return PortalPolicy.validate(candidate) } catch (_: Exception) {}
            } catch (_: Exception) {}
        }
        throw IllegalStateException("未找到校园门户，请连接校园网或粘贴完整地址")
    }
    private fun query(values: Map<String, String>) = values.entries.joinToString("&") {
        URLEncoder.encode(it.key, "UTF-8") + "=" + URLEncoder.encode(it.value, "UTF-8")
    }
    fun check(credentials: Credentials, force: Boolean = false): Pair<Boolean, String> {
        check(Operations.lock.tryLock()) { "已有检测正在进行，请稍后重试" }
        try {
            check(credentials.configured()) { "请先保存账号配置" }
            if (!force && online()) return true to "网络在线，无需登录"
            val account = credentials.account()
            val portal = try { detect() } catch (_: Exception) { PortalPolicy.validate(account.portal) }
            val uri = URI(portal); val base = "${uri.scheme}://${uri.rawAuthority}"
            val params = linkedMapOf<String, String>()
            (uri.rawQuery ?: "").split("&").filter { it.isNotBlank() }.forEach { pair ->
                val parts = pair.split("=", limit = 2); params[URLDecoder.decode(parts[0], "UTF-8")] = URLDecoder.decode(parts.getOrElse(1) { "" }, "UTF-8")
            }
            try {
                val response = get("$base/PortalJsonAction.do?${query(params)}&viewStatus=1")
                if (response.code == 200) {
                    val json = JSONObject(response.body)
                    for ((source, mapping) in listOf("serverForm" to mapOf("serverip" to "wlanacIp", "portalVer" to "version"),
                        "portalconfig" to mapOf("id" to "portalpageid", "timestamp" to "timestamp", "uuid" to "uuid"))) {
                        json.optJSONObject(source)?.let { values -> mapping.forEach { (key, target) -> if (!values.isNull(key)) params[target] = values.get(key).toString() } }
                    }
                }
            } catch (_: Exception) {}
            params["userid"] = "${account.id}@${account.operator}"; params["passwd"] = credentials.password()
            mapOf("wlanuseripv6" to "", "ssid" to "", "portaltype" to "0", "hostname" to "Android", "validateCode" to "", "bindCtrlId" to "").forEach { (k,v) -> params.putIfAbsent(k,v) }
            val response = get("$base/quickauth.do?${query(params)}")
            check(response.code == 200) { "认证请求返回 HTTP ${response.code}" }
            val result = try { JSONObject(response.body) } catch (_: Exception) { throw IllegalStateException("认证响应格式无效") }
            check(result.optString("code") == "0") { "校园网认证失败，请检查账号、密码和运营商" }
            val online = online()
            return online to if (online) "登录成功，网络已恢复" else "认证已通过，联网探针尚未通过"
        } finally { Operations.lock.unlock() }
    }
}
