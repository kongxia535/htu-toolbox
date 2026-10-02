package io.htu.toolbox

import java.net.URI
import java.util.concurrent.locks.ReentrantLock

internal object Operations { val lock = ReentrantLock() }

object PortalPolicy {
    fun validate(value: String): String {
        val uri = try { URI(value.trim()) } catch (_: Exception) { throw IllegalArgumentException("门户地址格式无效") }
        require(uri.scheme in listOf("http", "https") && uri.host == "10.101.2.194" &&
            uri.port == 6060 && uri.path == "/portal.do" && uri.userInfo == null && uri.fragment == null) {
            "门户须为 http(s)://10.101.2.194:6060/portal.do，保留完整参数"
        }
        return value.trim()
    }
    fun online(code: Int, body: String, expected: String?): Boolean =
        if (expected == null) code == 204 && body.isBlank() else code == 200 && body.trim() == expected
}
