use std::time::Duration;

use curl::easy::Easy;
use serde::de::DeserializeOwned;

#[derive(Debug, Default)]
pub enum Method<'a> {
    #[default]
    Get,
    Post(&'a [u8]),
    Put(&'a [u8]),
}

#[derive(Debug, Default)]
pub struct Request<'a> {
    pub url: &'a str,
    pub method: Method<'a>,
    pub timeout: Option<Duration>,
    pub ignore_timeout: bool,
}

impl Request<'_> {
    pub fn builder(url: &str) -> RequestBuilder<'_> {
        RequestBuilder::url(url)
    }
}

#[derive(Debug)]
pub struct RequestBuilder<'a> {
    url: &'a str,
    method: Option<Method<'a>>,
    timeout: Option<Duration>,
    ignore_timeout: bool,
}

impl<'a> RequestBuilder<'a> {
    pub fn url(url: &'a str) -> Self {
        Self {
            url,
            method: None,
            timeout: None,
            ignore_timeout: false,
        }
    }

    pub fn method(mut self, method: Method<'a>) -> Self {
        self.method = Some(method);
        self
    }

    pub fn timeout(mut self, timeout: Duration) -> Self {
        self.timeout = Some(timeout);
        self
    }

    pub fn ignore_timeout(mut self) -> Self {
        self.ignore_timeout = true;
        self
    }

    pub fn build(self) -> Request<'a> {
        Request {
            url: self.url,
            method: self.method.unwrap_or_default(),
            timeout: self.timeout,
            ignore_timeout: self.ignore_timeout,
        }
    }
}

impl<'a> From<RequestBuilder<'a>> for Request<'a> {
    fn from(val: RequestBuilder<'a>) -> Self {
        val.build()
    }
}

impl<'a> From<&'a str> for Request<'a> {
    fn from(val: &'a str) -> Self {
        Request::builder(val).build()
    }
}

pub struct HttpResponse<D = Vec<u8>> {
    pub code: u32,
    pub data: D,
    pub incomplete: bool,
}

pub fn curl<'a>(req: impl Into<Request<'a>>) -> crate::Result<HttpResponse> {
    let mut easy = Easy::new();
    let req: Request = req.into();
    easy.url(req.url)?;
    easy.connect_timeout(Duration::from_secs(3))?;
    easy.timeout(req.timeout.unwrap_or(Duration::from_secs(10)))?;
    match req.method {
        Method::Get => {}
        Method::Post(data) => {
            easy.post(true)?;
            easy.post_fields_copy(data)?;
        }
        Method::Put(data) => {
            easy.put(true)?;
            easy.post_fields_copy(data)?;
        }
    }
    if let Some(dur) = req.timeout {
        easy.timeout(dur)?;
    }

    let mut data = vec![];
    let mut incomplete = false;
    {
        let mut transfer = easy.transfer();
        transfer.write_function(|new_data| {
            data.extend(new_data);
            Ok(new_data.len())
        })?;
        if let Err(e) = transfer.perform() {
            if !e.is_operation_timedout() || !req.ignore_timeout {
                return Err(e.into());
            }
            incomplete = true;
        };
    }

    Ok(HttpResponse {
        code: easy.response_code()?,
        data,
        incomplete,
    })
}

pub fn curl_json<'a, D: DeserializeOwned>(
    req: impl Into<Request<'a>>,
) -> crate::Result<HttpResponse<D>> {
    let response = curl(req)?;
    if response.incomplete {
        return Err(crate::Error::other(
            "HTTP response timed out before completion",
        ));
    }
    if !(200..300).contains(&response.code) {
        return Err(crate::Error::other(format!(
            "HTTP status {}",
            response.code
        )));
    }
    let data: D = serde_json::from_slice(&response.data)?;
    Ok(HttpResponse {
        code: response.code,
        data,
        incomplete: false,
    })
}

#[cfg(test)]
mod tests {
    use super::*;
    use std::{
        io::{Read, Write},
        net::TcpListener,
        thread,
    };

    fn partial_server() -> (String, thread::JoinHandle<()>) {
        let listener = TcpListener::bind("127.0.0.1:0").unwrap();
        let url = format!("http://{}/", listener.local_addr().unwrap());
        let handle = thread::spawn(move || {
            let (mut stream, _) = listener.accept().unwrap();
            let mut buffer = [0u8; 1024];
            stream.read(&mut buffer).unwrap();
            stream
                .write_all(b"HTTP/1.1 200 OK\r\nContent-Length: 100\r\n\r\npartial")
                .unwrap();
            thread::sleep(Duration::from_millis(150));
        });
        (url, handle)
    }

    #[test]
    fn timeout_is_an_error_by_default() {
        let (url, handle) = partial_server();
        let result = curl(Request::builder(&url).timeout(Duration::from_millis(50)));
        assert!(matches!(result, Err(crate::Error::Curl(error)) if error.is_operation_timedout()));
        handle.join().unwrap();
    }

    #[test]
    fn explicit_partial_response_is_marked_incomplete() {
        let (url, handle) = partial_server();
        let result = curl(
            Request::builder(&url)
                .timeout(Duration::from_millis(50))
                .ignore_timeout(),
        )
        .unwrap();
        assert!(result.incomplete);
        assert_eq!(result.data, b"partial");
        handle.join().unwrap();
    }
}
