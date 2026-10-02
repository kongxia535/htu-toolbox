use clap::Parser;
use color_eyre::Section;
use config::{Config, NetLoginCfg};
use console::{style, Emoji};
use eyre::Context;
use htu_toolbox_lib::{config::NetLoginAccount, net::Operator};
use net::{Net, NetAccArgs};
use std::{io::IsTerminal, process::ExitCode};

mod config;
mod net;

#[derive(Debug, Clone, clap::Parser)]
struct Args {
    /// 完成后等待回车（仅用于交互式终端）
    #[arg(long)]
    pause: bool,
    #[clap(subcommand)]
    cmd: Option<SubCmd>,
}

#[derive(Debug, Clone, clap::Subcommand)]
enum SubCmd {
    /// 校园网管理
    Net {
        #[clap(subcommand)]
        cmd: Net,
    },
}

impl SubCmd {
    pub fn execute(self) -> eyre::Result<()> {
        match self {
            SubCmd::Net {
                cmd:
                    net::Net::Login(NetAccArgs {
                        id: Some(id),
                        password: Some(pwd),
                        operator: Some(operator),
                    }),
            } => {
                if htu_toolbox_lib::net::ping().is_ok() {
                    println!(
                        "{} {}",
                        Emoji::new("✅", "[!]"),
                        style("网络可正常访问，无须登录校园网")
                    );
                    return Ok(());
                }
                println!(
                    "{} {}",
                    Emoji::new("🔎", "[?]",),
                    style("获取登录页路径...")
                );
                let req = htu_toolbox_lib::net::AuthRequest::create(None)
                    .with_context(|| "登录页请求失败")?;
                let opr: Operator = operator.into();

                println!("{} {}", Emoji::new("🔌", "[+]",), style("登录校园网..."));
                let result = req
                    .quick_auth(id, pwd, opr)
                    .with_context(|| "校园网登录时发生错误")?;

                if !result.success() {
                    eyre::bail!(
                        "校园网登录失败, 错误码 {}, 错误消息: {}",
                        result.code,
                        result.message.unwrap_or_default()
                    )
                }

                println!("{} {}", Emoji::new("✅", "[√]"), style("校园网登录成功"));
            }
            SubCmd::Net {
                cmd: net::Net::Logout,
            } => {
                println!("{} {}", Emoji::new("🔌", "[-]",), style("登出校园网..."));
                let resp = htu_toolbox_lib::net::logout()
                    .with_context(|| "登出请求失败")
                    .with_suggestion(|| "或许你还没有连上校园网？")?;

                if !resp.success() {
                    eyre::bail!(
                        "校园网登出失败, 错误码 {}, 错误消息: {}",
                        resp.result,
                        resp.msg,
                    )
                }
            }
            SubCmd::Net {
                cmd: net::Net::Set(args),
            } => {
                let mut cfg = Config::load().with_context(|| "配置文件加载失败")?;
                if args.id.is_none() {
                    let account = net::account_guide()?;
                    cfg.net_login = Some(NetLoginCfg { account })
                } else {
                    cfg.net_login = Some(NetLoginCfg {
                        account: NetLoginAccount {
                            id: args.id.unwrap(),
                            password: args.password.unwrap(),
                            operator: args.operator.unwrap().into(),
                        },
                    })
                }
                cfg.save().with_context(|| "配置文件保存失败")?;
                println!(
                    "{} {}",
                    Emoji::new("✅", "[√]"),
                    style("校园网账号设置成功")
                );
            }
            _ => eyre::bail!("incorrect cmd args"),
        }

        Ok(())
    }
}

fn wait_stdin() {
    let mut input = String::new();
    std::io::stdin().read_line(&mut input).unwrap();
}

fn run() -> eyre::Result<()> {
    color_eyre::install()?;

    let args = Args::parse();
    let mut cfg = Config::load().with_context(|| "配置文件加载失败")?;
    let processed = if let Some(arg) = args.cmd {
        match arg {
            SubCmd::Net {
                cmd: net::Net::Login(mut net_login_args),
            } => {
                if net_login_args.id.is_none() {
                    cfg.ensure_net_login_account()
                        .with_context(|| "配置文件创建失败")?;
                    net_login_args = cfg.net_login.unwrap().into();
                }
                SubCmd::Net {
                    cmd: net::Net::Login(net_login_args),
                }
            }
            cmd => cmd,
        }
    } else {
        cfg.into_sub_cmd()?
    };

    processed.execute().with_context(|| "指令执行失败")?;
    if args.pause && std::io::stdin().is_terminal() {
        println!("按回车键继续...");
        wait_stdin();
    }
    Ok(())
}

fn main() -> ExitCode {
    match run() {
        Ok(()) => ExitCode::SUCCESS,
        Err(error) => {
            eprintln!("{error:?}");
            ExitCode::FAILURE
        }
    }
}
