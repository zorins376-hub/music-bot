$ErrorActionPreference = "Stop"

$jdk = "C:\Users\sherh\Downloads\java-1.8.0-openjdk-1.8.0.482.b08-1.win.jdk.x86_64"
$javaExe = Join-Path $jdk "bin\java.exe"
$javacExe = Join-Path $jdk "bin\javac.exe"

if (-not (Test-Path $javaExe)) {
    throw "JDK bin not found: $javaExe"
}

[Environment]::SetEnvironmentVariable("JAVA_HOME", $jdk, "User")
$userPath = [Environment]::GetEnvironmentVariable("Path", "User")
$jdkBin = Join-Path $jdk "bin"

if ([string]::IsNullOrEmpty($userPath)) {
    $newUserPath = $jdkBin
} elseif ($userPath -notlike "*$jdkBin*") {
    $newUserPath = "$jdkBin;$userPath"
} else {
    $newUserPath = $userPath
}

[Environment]::SetEnvironmentVariable("Path", $newUserPath, "User")
$env:JAVA_HOME = $jdk
if ($env:Path -notlike "*$jdkBin*") {
    $env:Path = "$jdkBin;" + $env:Path
}

Write-Output "JAVA_HOME=$env:JAVA_HOME"
& $javaExe -version
& $javacExe -version
