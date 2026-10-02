#!/usr/bin/env python3
"""Build a debug APK using an installed, verified SDK and Kotlin compiler.

This path has no Maven dependency downloads. Gradle remains the normal build.
"""
from __future__ import annotations

import argparse
import configparser
import os
from pathlib import Path
import shutil
import subprocess
import xml.etree.ElementTree as ET
import zipfile

ROOT = Path(__file__).resolve().parents[1]
ANDROID = "{http://schemas.android.com/apk/res/android}"


def run(*args: str | Path) -> None:
    subprocess.run([str(arg) for arg in args], check=True)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sdk", type=Path, default=os.environ.get("ANDROID_HOME"))
    parser.add_argument("--kotlin", type=Path, default=os.environ.get("KOTLIN_HOME"))
    parser.add_argument(
        "--build-tools",
        default="36.0.0",
        help="Build Tools 36 includes D8 compatible with Kotlin 2.1",
    )
    parser.add_argument("--compile-sdk", default="36")
    parser.add_argument(
        "--junit",
        type=Path,
        help="JUnit 4.13.2 jar for running the existing unit tests",
    )
    parser.add_argument(
        "--hamcrest", type=Path, help="Hamcrest core jar required by JUnit"
    )
    args = parser.parse_args()
    if not args.sdk or not args.kotlin:
        parser.error("Set ANDROID_HOME/KOTLIN_HOME or pass --sdk and --kotlin")
    sdk = args.sdk.resolve()
    kotlin = args.kotlin.resolve()
    tools = sdk / "build-tools" / args.build_tools
    framework = sdk / ("platforms/android-" + args.compile_sdk) / "android.jar"
    compiler = kotlin / ("bin/kotlinc.bat" if os.name == "nt" else "bin/kotlinc")
    suffix = ".exe" if os.name == "nt" else ""
    script_suffix = ".bat" if os.name == "nt" else ""
    aapt = tools / ("aapt2" + suffix)
    for file in [framework, compiler, aapt]:
        if not file.exists():
            parser.error(f"Missing tool: {file}")
    version = configparser.ConfigParser(interpolation=None)
    version.read_string("[app]\n" + (ROOT / "android/version.properties").read_text())
    version_code = version.getint("app", "versionCode")
    version_name = version.get("app", "versionName")
    if not 1 <= version_code <= 2100000000 or not version_name.strip():
        parser.error("Invalid version in android/version.properties")
    build = ROOT / "android/app/build/standalone"
    if build.exists():
        shutil.rmtree(build)
    for directory in ["java", "classes", "dex", "tests"]:
        (build / directory).mkdir(parents=True)
    ET.register_namespace("android", "http://schemas.android.com/apk/res/android")
    manifest = ET.parse(ROOT / "android/app/src/main/AndroidManifest.xml")
    manifest.getroot().set("package", "io.htu.toolbox")
    manifest.getroot().set(ANDROID + "versionCode", str(version_code))
    manifest.getroot().set(ANDROID + "versionName", version_name)
    uses_sdk = ET.Element(
        "uses-sdk",
        {
            ANDROID + "minSdkVersion": "26",
            ANDROID + "targetSdkVersion": args.compile_sdk,
        },
    )
    manifest.getroot().insert(0, uses_sdk)
    manifest.write(
        build / "AndroidManifest.xml", encoding="utf-8", xml_declaration=True
    )
    run(
        aapt,
        "compile",
        "--dir",
        ROOT / "android/app/src/main/res",
        "-o",
        build / "resources.zip",
    )
    run(
        aapt,
        "link",
        "-o",
        build / "resources.apk",
        "-I",
        framework,
        "--manifest",
        build / "AndroidManifest.xml",
        "--java",
        build / "java",
        build / "resources.zip",
    )
    run(
        "java",
        "-m",
        "jdk.compiler/com.sun.tools.javac.Main",
        "-source",
        "8",
        "-target",
        "8",
        "-bootclasspath",
        framework,
        "-d",
        build / "classes",
        *sorted((build / "java").rglob("*.java")),
    )
    kotlin_lib = kotlin / "lib/kotlin-stdlib.jar"
    classpath = os.pathsep.join(map(str, [framework, build / "classes"]))
    run(
        compiler,
        "-jvm-target",
        "1.8",
        "-classpath",
        classpath,
        "-d",
        build / "classes",
        *sorted((ROOT / "android/app/src/main/java").rglob("*.kt")),
    )
    with zipfile.ZipFile(build / "classes.jar", "w") as archive:
        for file in (build / "classes").rglob("*"):
            if file.is_file():
                archive.write(file, file.relative_to(build / "classes"))
    run(
        tools / ("d8" + script_suffix),
        "--lib",
        framework,
        "--min-api",
        "26",
        "--output",
        build / "dex",
        build / "classes.jar",
        kotlin_lib,
    )
    unsigned = build / "unsigned.apk"
    shutil.copy2(build / "resources.apk", unsigned)
    with zipfile.ZipFile(unsigned, "a") as apk:
        for dex in (build / "dex").glob("*.dex"):
            apk.write(dex, dex.name)
    run(tools / ("zipalign" + suffix), "-f", "4", unsigned, build / "aligned.apk")
    # The standard public Android debug identity is for testing, never production.
    keystore = ROOT / "android/.local/debug.keystore"
    keystore.parent.mkdir(exist_ok=True)
    if not keystore.exists():
        run(
            "keytool",
            "-genkeypair",
            "-keystore",
            keystore,
            "-storepass",
            "android",
            "-keypass",
            "android",
            "-alias",
            "androiddebugkey",
            "-dname",
            "CN=Android Debug,O=Android,C=US",
            "-keyalg",
            "RSA",
            "-keysize",
            "2048",
            "-validity",
            "10000",
        )
    artifact = ROOT / "dist/htu-connect-debug.apk"
    artifact.parent.mkdir(exist_ok=True)
    run(
        tools / ("apksigner" + script_suffix),
        "sign",
        "--ks",
        keystore,
        "--ks-pass",
        "pass:android",
        "--key-pass",
        "pass:android",
        "--out",
        artifact,
        build / "aligned.apk",
    )
    run(tools / ("apksigner" + script_suffix), "verify", "--verbose", artifact)
    if args.junit and args.hamcrest:
        cp = os.pathsep.join(
            map(str, [args.junit, args.hamcrest, build / "classes", kotlin_lib])
        )
        run(
            compiler,
            "-jvm-target",
            "1.8",
            "-classpath",
            cp,
            "-d",
            build / "tests",
            *sorted((ROOT / "android/app/src/test/java").rglob("*.kt")),
        )
        run(
            "java",
            "-classpath",
            cp + os.pathsep + str(build / "tests"),
            "org.junit.runner.JUnitCore",
            "io.htu.toolbox.PortalPolicyTest",
        )
    print(f"APK built and signature verified: {artifact}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
