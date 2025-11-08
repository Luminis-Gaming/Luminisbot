@echo off
REM Self-sign the executable to reduce Windows SmartScreen warnings
REM This doesn't eliminate the warning but can help for internal distribution

echo ================================================
echo Self-Signing LuminisbotCompanion.exe
echo ================================================
echo.

REM Check if signtool exists
where signtool >nul 2>&1
if errorlevel 1 (
    echo ERROR: signtool not found
    echo.
    echo You need to install Windows SDK to use signtool.
    echo Download from: https://developer.microsoft.com/en-us/windows/downloads/windows-sdk/
    echo.
    pause
    exit /b 1
)

REM Create a self-signed certificate (only needed once)
echo Creating self-signed certificate...
powershell -Command "& {$cert = New-SelfSignedCertificate -Type CodeSigningCert -Subject 'CN=Luminis Gaming' -CertStoreLocation Cert:\CurrentUser\My; Export-Certificate -Cert $cert -FilePath LuminisGaming.cer}"

if not exist "LuminisGaming.cer" (
    echo ERROR: Failed to create certificate
    pause
    exit /b 1
)

echo Certificate created: LuminisGaming.cer
echo.

REM Sign the executable
echo Signing executable...
signtool sign /f LuminisGaming.cer /fd SHA256 /t http://timestamp.digicert.com dist\LuminisbotCompanion.exe

if errorlevel 1 (
    echo.
    echo ERROR: Failed to sign executable
    pause
    exit /b 1
)

echo.
echo ================================================
echo SUCCESS! Executable signed.
echo ================================================
echo.
echo Note: Self-signed certificates still show a warning, but:
echo - The warning is less severe
echo - Shows "Luminis Gaming" as publisher
echo - Users can add to trusted certificates
echo.
pause
