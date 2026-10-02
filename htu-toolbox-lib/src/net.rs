use core::str;
use std::{str::FromStr, sync::LazyLock, time::Duration};

use serde::{Deserialize, Serialize};
use url::Url;

use crate::{
    http::{self, Request},
    Result,
};

pub static INDEX_URL_REGEX: LazyLock<regex::Regex> =
    LazyLock::new(|| regex::Regex::new(r#"https?://[^\s"'<>]+/portal\.do\?[^\s"'<>]+"#).unwrap());

#[derive(Debug, Clone, Copy, Deserialize, Serialize)]
pub enum Operator {
    #[serde(rename = "yd")]
    Mobie,
    #[serde(rename = "lt")]
    Unicom,
    #[serde(rename = "dx")]
    Telecom,
    #[serde(rename = "hsd")]
    Campus,
}

impl AsRef<str> for Operator {
    fn as_ref(&self) -> &str {
        match self {
            Operator::Mobie => "yd",
            Operator::Unicom => "lt",
            Operator::Telecom => "dx",
            Operator::Campus => "hsd",
        }
    }
}

impl FromStr for Operator {
    type Err = ();

    fn from_str(s: &str) -> std::result::Result<Self, Self::Err> {
        match s {
            "yd" => Ok(Operator::Mobie),
            "lt" => Ok(Operator::Unicom),
            "dx" => Ok(Operator::Telecom),
            "hsd" => Ok(Operator::Campus),
            _ => Err(()),
        }
    }
}

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct AuthResponse {
    pub code: String,
    pub message: Option<String>,
}

impl AuthResponse {
    pub fn success(&self) -> bool {
        self.code == "0"
    }
}

pub struct AuthRequest {
    base_url: String,
    params: Vec<(String, String)>,
}

impl AuthRequest {
    pub fn create(index_url: Option<&str>) -> Result<Self> {
        let index_data = http::curl(
            Request::builder(index_url.unwrap_or("http://192.168.1.1"))
                .timeout(Duration::from_secs(5)),
        )?;
        let index_content = String::from_utf8(index_data.data)?;
        let redirect_url = match INDEX_URL_REGEX
            .captures(index_content.as_ref())
            .and_then(|caps| caps.get(0).map(|m| m.as_str()))
        {
            Some(r) => r,
            None => return Err(crate::Error::InvalidIndexContent(index_content)),
        };
        let decoded = redirect_url.replace("&amp;", "&");
        let url = validate_portal_url(&decoded)?;
        Ok(Self {
            base_url: format!(
                "{}://{}:{}",
                url.scheme(),
                url.host_str().ok_or(url::ParseError::EmptyHost)?,
                url.port().unwrap_or(80)
            ),
            params: url
                .query_pairs()
                .map(|(key, value)| (key.into_owned(), value.into_owned()))
                .collect(),
        })
    }

    pub fn quick_auth(
        &self,
        userid: impl AsRef<str>,
        passwd: impl AsRef<str>,
        operator: impl AsRef<str>,
    ) -> crate::Result<AuthResponse> {
        let mut url = Url::from_str(&format!("{}/quickauth.do", self.base_url))?;
        let mut userid = userid.as_ref().to_owned();
        if !userid.contains('@') {
            userid.push('@');
            userid.push_str(operator.as_ref());
        }
        url.query_pairs_mut()
            .extend_pairs(&self.params)
            .append_pair("userid", &userid)
            .append_pair("passwd", passwd.as_ref());

        Ok(http::curl_json(url.as_str())?.data)
    }
}

#[derive(Debug, Serialize, Deserialize, Default)]
pub struct LogoutResponse {
    pub result: i32,
    pub msg: String,
}

impl LogoutResponse {
    pub fn success(&self) -> bool {
        self.result == 1
    }
}

pub fn ping() -> std::io::Result<()> {
    for (url, expected) in [
        (
            "http://www.msftconnecttest.com/connecttest.txt",
            Some(&b"Microsoft Connect Test"[..]),
        ),
        ("http://connectivitycheck.gstatic.com/generate_204", None),
    ] {
        if let Ok(response) = http::curl(Request::builder(url).timeout(Duration::from_secs(3))) {
            if probe_is_online(response.code, &response.data, expected) {
                return Ok(());
            }
        }
    }
    Err(std::io::Error::other(
        "Internet probe failed or captive portal intercepted it",
    ))
}

pub fn probe_is_online(code: u32, body: &[u8], expected: Option<&[u8]>) -> bool {
    match expected {
        Some(expected) => code == 200 && body == expected,
        None => code == 204 && body.is_empty(),
    }
}

pub fn validate_portal_url(value: &str) -> Result<Url> {
    let url = Url::parse(value)?;
    if !matches!(url.scheme(), "http" | "https")
        || url.host_str() != Some("10.101.2.194")
        || url.port_or_known_default() != Some(6060)
        || url.path() != "/portal.do"
        || !url.username().is_empty()
        || url.password().is_some()
        || url.fragment().is_some()
    {
        return Err(crate::Error::other("Unsupported campus portal URL"));
    }
    Ok(url)
}

#[cfg(test)]
mod tests {
    use super::*;
    #[test]
    fn captive_pages_are_not_online() {
        assert!(!probe_is_online(302, b"login", None));
        assert!(!probe_is_online(
            200,
            b"<html>login</html>",
            Some(b"Microsoft Connect Test")
        ));
        assert!(probe_is_online(
            200,
            b"Microsoft Connect Test",
            Some(b"Microsoft Connect Test")
        ));
        assert!(probe_is_online(204, b"", None));
    }
    #[test]
    fn portal_validation_rejects_other_destinations() {
        assert!(validate_portal_url("http://10.101.2.194:6060/portal.do?test=1").is_ok());
        for url in [
            "http://8.8.8.8:6060/portal.do",
            "http://10.101.2.194:80/portal.do",
            "http://10.101.2.194:6060/nope",
            "http://user:pass@10.101.2.194:6060/portal.do",
        ] {
            assert!(validate_portal_url(url).is_err());
        }
    }
}

pub fn logout() -> Result<LogoutResponse> {
    Ok(http::curl_json(
        Request::builder("http://10.101.2.205/loginOut")
            .method(http::Method::Post(&[]))
            .timeout(Duration::from_secs(2)),
    )?
    .data)
}
