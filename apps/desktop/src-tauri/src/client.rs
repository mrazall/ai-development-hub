use crate::{
    types::{AccountProfile, AppError, ErrorCode, FoundLogin, HubInfo, LoginResult, Notification},
    url::normalize_hub_url,
};
use reqwest::Client;
use serde::Deserialize;

#[derive(Deserialize)]
struct Token {
    access_token: String,
}
#[derive(Deserialize)]
struct Me {
    username: String,
    role: Option<String>,
}
pub async fn check_hub(raw: &str) -> Result<HubInfo, AppError> {
    let url = normalize_hub_url(raw)?;
    let c = Client::new();
    let health = c
        .get(format!("{url}/api/v0/health"))
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Hub health request failed"))?;
    if !health.status().is_success() {
        return Err(AppError::new(ErrorCode::Http, "Hub health check failed"));
    }
    #[derive(Deserialize)]
    struct Info {
        version: Option<String>,
        demo: Option<bool>,
    }
    let info: Info = c
        .get(format!("{url}/api/v0/system/info"))
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Hub info request failed"))?
        .json()
        .await
        .map_err(|_| AppError::new(ErrorCode::NotAHub, "The address is not an AI Hub"))?;
    Ok(HubInfo {
        url,
        version: info.version.unwrap_or_else(|| "unknown".into()),
        demo: info.demo.unwrap_or(false),
    })
}
/// The device sign-in the hub sets on login and rotates on refresh (30 days from the last use).
fn refresh_cookie(response: &reqwest::Response) -> Option<String> {
    response
        .headers()
        .get_all(reqwest::header::SET_COOKIE)
        .iter()
        .filter_map(|value| value.to_str().ok())
        .find_map(|value| value.strip_prefix("aihub_refresh="))
        .map(|rest| rest.split(';').next().unwrap_or_default().to_owned())
        .filter(|value| !value.is_empty())
}

/// A new access token for the stored device sign-in; returns it and the rotated refresh token.
pub async fn refresh(raw: &str, refresh: &str) -> Result<(String, Option<String>), AppError> {
    let url = normalize_hub_url(raw)?;
    let response = Client::new()
        .post(format!("{url}/api/v0/auth/refresh"))
        .header(reqwest::header::COOKIE, format!("aihub_refresh={refresh}"))
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Refresh request failed"))?;
    if response.status() == reqwest::StatusCode::UNAUTHORIZED {
        return Err(AppError::new(ErrorCode::Unauthorized, "Signed out"));
    }
    if !response.status().is_success() {
        return Err(AppError::new(ErrorCode::Http, "Refresh failed"));
    }
    let rotated = refresh_cookie(&response);
    let token: Token = response
        .json()
        .await
        .map_err(|_| AppError::new(ErrorCode::Http, "Invalid refresh response"))?;
    Ok((token.access_token, rotated))
}

pub async fn login(
    raw: &str,
    user: &str,
    password: &str,
) -> Result<(LoginResult, String, Option<String>), AppError> {
    let url = normalize_hub_url(raw)?;
    let response = Client::new()
        .post(format!("{url}/api/v0/auth/login"))
        .json(&serde_json::json!({"username": user, "password": password}))
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Login request failed"))?;
    if response.status() == reqwest::StatusCode::UNAUTHORIZED {
        return Err(AppError::new(
            ErrorCode::Unauthorized,
            "Invalid credentials",
        ));
    }
    if !response.status().is_success() {
        return Err(AppError::new(ErrorCode::Http, "Login failed"));
    }
    let device = refresh_cookie(&response);
    let token: Token = response
        .json()
        .await
        .map_err(|_| AppError::new(ErrorCode::Http, "Invalid login response"))?;
    let me: Me = Client::new()
        .get(format!("{url}/api/v0/auth/me"))
        .bearer_auth(&token.access_token)
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Profile request failed"))?
        .json()
        .await
        .map_err(|_| AppError::new(ErrorCode::Http, "Invalid profile response"))?;
    Ok((
        LoginResult {
            username: me.username,
            is_admin: me.role.as_deref() == Some("admin"),
        },
        token.access_token,
        device,
    ))
}

fn authenticated(token: &str) -> Client {
    let _ = token;
    Client::new()
}

#[derive(Deserialize)]
struct WorkerOut {
    id: String,
    status: String,
    worker_token: Option<String>,
    #[serde(alias = "worker_version")]
    version: Option<String>,
    #[serde(alias = "activeAgents", alias = "active_sessions")]
    active_agents: Option<u32>,
}

pub async fn register_worker(
    raw_url: &str,
    token: &str,
    id: &str,
    engines: &[String],
) -> Result<String, AppError> {
    let url = normalize_hub_url(raw_url)?;
    let response = authenticated(token)
        .post(format!("{url}/api/v0/workers"))
        .bearer_auth(token)
        .json(&serde_json::json!({"id": id, "host": id, "kind": "desktop", "labels": engines}))
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Worker registration failed"))?;
    if response.status() == reqwest::StatusCode::UNAUTHORIZED {
        return Err(AppError::new(ErrorCode::Unauthorized, "Hub login expired"));
    }
    if response.status() == reqwest::StatusCode::FORBIDDEN {
        return Err(AppError::new(
            ErrorCode::Forbidden,
            "Administrator access is required",
        ));
    }
    if !response.status().is_success() {
        return Err(AppError::new(ErrorCode::Http, "Worker registration failed"));
    }
    let worker: WorkerOut = response
        .json()
        .await
        .map_err(|_| AppError::new(ErrorCode::Http, "Invalid worker registration response"))?;
    let _ = (&worker.id, &worker.status);
    worker
        .worker_token
        .ok_or_else(|| AppError::new(ErrorCode::Http, "Hub did not return a worker token"))
}

pub async fn worker_status(
    raw_url: &str,
    token: Option<&str>,
    worker_id: Option<&str>,
) -> Result<(bool, String, u32, Option<String>, u32), AppError> {
    let url = normalize_hub_url(raw_url)?;
    let client = Client::new();
    let mut health = client.get(format!("{url}/api/v0/health"));
    if let Some(value) = token {
        health = health.bearer_auth(value);
    }
    let health_ok = health
        .send()
        .await
        .map(|r| r.status().is_success())
        .unwrap_or(false);
    let Some(id) = worker_id else {
        return Ok((health_ok, "unknown".into(), 0, None, 0));
    };
    let Some(token) = token else {
        return Ok((health_ok, "unknown".into(), 0, None, 0));
    };
    let worker_response = client
        .get(format!("{url}/api/v0/workers"))
        .bearer_auth(token)
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Worker status request failed"))?;
    if worker_response.status() == reqwest::StatusCode::UNAUTHORIZED {
        return Err(AppError::new(ErrorCode::Unauthorized, "Sign-in expired"));
    }
    let workers: Vec<WorkerOut> = worker_response
        .json()
        .await
        .map_err(|_| AppError::new(ErrorCode::Http, "Invalid worker status response"))?;
    let worker = workers.into_iter().find(|worker| worker.id == id);
    let state = worker
        .as_ref()
        .map(|worker| worker.status.clone())
        .unwrap_or_else(|| "offline".into());
    let version = worker.as_ref().and_then(|worker| worker.version.clone());
    let active_agents = worker.and_then(|worker| worker.active_agents).unwrap_or(0);
    let notifications = client
        .get(format!("{url}/api/v0/notifications?unread=true&limit=100"))
        .bearer_auth(token)
        .send()
        .await
        .ok()
        .map(|response| async { response.json::<Vec<Notification>>().await.ok() });
    let notifications = match notifications {
        Some(future) => future.await.unwrap_or_default(),
        None => Vec::new(),
    };
    let approvals = notifications
        .iter()
        .filter(|item| {
            item.kind.as_deref() == Some("approval")
                || item.kind.as_deref() == Some("permission_request")
        })
        .count() as u32;
    Ok((health_ok, state, approvals, version, active_agents))
}

pub async fn delete_worker(raw_url: &str, token: &str, id: &str) -> Result<(), AppError> {
    let url = normalize_hub_url(raw_url)?;
    let response = Client::new()
        .delete(format!("{url}/api/v0/workers/{id}"))
        .bearer_auth(token)
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Worker disconnect request failed"))?;
    if response.status().is_success() || response.status() == reqwest::StatusCode::NOT_FOUND {
        Ok(())
    } else {
        Err(AppError::new(
            ErrorCode::Http,
            "Worker disconnect request failed",
        ))
    }
}

pub async fn notifications(raw_url: &str, token: &str) -> Result<Vec<Notification>, AppError> {
    let url = normalize_hub_url(raw_url)?;
    let response = Client::new()
        .get(format!("{url}/api/v0/notifications?limit=100"))
        .bearer_auth(token)
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Notification request failed"))?;
    if response.status() == reqwest::StatusCode::UNAUTHORIZED {
        return Err(AppError::new(ErrorCode::Unauthorized, "Hub login expired"));
    }
    if !response.status().is_success() {
        return Err(AppError::new(
            ErrorCode::Http,
            "Notification request failed",
        ));
    }
    response
        .json()
        .await
        .map_err(|_| AppError::new(ErrorCode::Http, "Invalid notification response"))
}

pub async fn found_logins(raw_url: &str, token: &str) -> Result<Vec<FoundLogin>, AppError> {
    let url = normalize_hub_url(raw_url)?;
    let response = Client::new()
        .get(format!("{url}/api/v0/accounts/found-logins"))
        .bearer_auth(token)
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Found logins request failed"))?;
    if response.status() == reqwest::StatusCode::UNAUTHORIZED {
        return Err(AppError::new(ErrorCode::Unauthorized, "Hub login expired"));
    }
    response
        .json()
        .await
        .map_err(|_| AppError::new(ErrorCode::Http, "Invalid found logins response"))
}
pub async fn accounts(
    raw_url: &str,
    token: &str,
    worker_id: &str,
) -> Result<Vec<AccountProfile>, AppError> {
    let url = normalize_hub_url(raw_url)?;
    Client::new()
        .get(format!("{url}/api/v0/accounts?worker_id={worker_id}"))
        .bearer_auth(token)
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Accounts request failed"))?
        .json()
        .await
        .map_err(|_| AppError::new(ErrorCode::Http, "Invalid accounts response"))
}
pub async fn create_subscription(
    raw_url: &str,
    token: &str,
    worker_id: &str,
    engine: &str,
    adopt: bool,
) -> Result<AccountProfile, AppError> {
    let url = normalize_hub_url(raw_url)?;
    let kind = match engine {
        "claude" => "claude_code_subscription",
        "codex" => "codex_subscription",
        _ => {
            return Err(AppError::new(
                ErrorCode::InvalidEngine,
                "Invalid subscription engine",
            ))
        }
    };
    Client::new()
        .post(format!("{url}/api/v0/accounts"))
        .bearer_auth(token)
        .json(
            &serde_json::json!({"kind": kind, "worker_id": worker_id, "adopt_found_login": adopt}),
        )
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Account creation failed"))?
        .json()
        .await
        .map_err(|_| AppError::new(ErrorCode::Http, "Invalid account response"))
}
pub async fn login_command(raw_url: &str, token: &str, id: &str) -> Result<String, AppError> {
    let url = normalize_hub_url(raw_url)?;
    let value: serde_json::Value = Client::new()
        .get(format!("{url}/api/v0/accounts/{id}/login-command"))
        .bearer_auth(token)
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Login command request failed"))?
        .json()
        .await
        .map_err(|_| AppError::new(ErrorCode::Http, "Invalid login command response"))?;
    value
        .get("shell")
        .and_then(|v| v.as_str())
        .map(ToOwned::to_owned)
        .ok_or_else(|| AppError::new(ErrorCode::Http, "Hub did not return a login command"))
}
pub async fn login_started(raw_url: &str, token: &str, id: &str) -> Result<(), AppError> {
    let url = normalize_hub_url(raw_url)?;
    let response = Client::new()
        .post(format!("{url}/api/v0/accounts/{id}/login-started"))
        .bearer_auth(token)
        .send()
        .await
        .map_err(|_| AppError::new(ErrorCode::Network, "Login start request failed"))?;
    if response.status().is_success() {
        Ok(())
    } else {
        Err(AppError::new(ErrorCode::Http, "Login start request failed"))
    }
}
