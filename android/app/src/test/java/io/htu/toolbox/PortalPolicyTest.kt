package io.htu.toolbox
import org.junit.Assert.*
import org.junit.Test
class PortalPolicyTest {
    @Test fun acceptsCampusPortal() { assertEquals("http://10.101.2.194:6060/portal.do?test=1", PortalPolicy.validate("http://10.101.2.194:6060/portal.do?test=1")) }
    @Test fun rejectsWrongHostPortPathAndCredentials() {
        for (url in listOf("http://8.8.8.8:6060/portal.do", "http://10.101.2.194:80/portal.do", "http://10.101.2.194:6060/nope", "http://user:pass@10.101.2.194:6060/portal.do")) {
            try { PortalPolicy.validate(url); fail("Accepted $url") } catch (_: IllegalArgumentException) {}
        }
    }
    @Test fun captivePageIsNotOnline() {
        assertFalse(PortalPolicy.online(302,"login",null));assertFalse(PortalPolicy.online(200,"login","Microsoft Connect Test"))
        assertTrue(PortalPolicy.online(200,"Microsoft Connect Test","Microsoft Connect Test"));assertTrue(PortalPolicy.online(204,"",null))
    }
}
