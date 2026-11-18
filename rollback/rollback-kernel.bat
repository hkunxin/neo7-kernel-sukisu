@echo off
setlocal enabledelayedexpansion
chcp 437 >nul

REM ============================================================
REM  054  rollback: restore stock boot + init_boot
REM  Run this when the custom kernel does not boot.
REM  Enter bootloader manually: hold Power+VolUp (or Power+VolDown)
REM ============================================================

set "IMG=E:\neo7\_analysis\img"
set "FB=E:\neo7\flash\bin\fastboot.exe"

set "BOOT_SHA=281aaa520d9008a1f82da7ee0a3fb0d546f27b05c39e285796015d98f2665b48"
set "INIT_SHA=a0a95ce9f2f26b2bc63f1aea81a112c4a62259c3d0aaa7a2504a1c8c9c59d188"

echo.
echo [1/4] Checking backup images ...
if not exist "%IMG%\boot.img"      ( echo [FAIL] missing %IMG%\boot.img & goto :end )
if not exist "%IMG%\init_boot.img" ( echo [FAIL] missing %IMG%\init_boot.img & goto :end )

echo.
echo [2/4] Checking sha256 ...
for /f "skip=1 tokens=*" %%H in ('certutil -hashfile "%IMG%\boot.img" SHA256') do (
    if not defined B_HASH set "B_HASH=%%H"
)
for /f "skip=1 tokens=*" %%H in ('certutil -hashfile "%IMG%\init_boot.img" SHA256') do (
    if not defined I_HASH set "I_HASH=%%H"
)
set "B_HASH=%B_HASH: =%"
set "I_HASH=%I_HASH: =%"
if /i not "%B_HASH%"=="%BOOT_SHA%" ( echo [FAIL] boot.img hash mismatch: %B_HASH% & goto :end )
if /i not "%I_HASH%"=="%INIT_SHA%" ( echo [FAIL] init_boot.img hash mismatch: %I_HASH% & goto :end )
echo [OK] both match the backup baseline

echo.
echo [3/4] Checking device in fastboot ...
"%FB%" devices
echo.
echo If the list above is empty, enter bootloader and re-run this script.
pause

echo.
echo [4/4] Flashing stock boot + init_boot ...
"%FB%" flash boot     "%IMG%\boot.img"
if errorlevel 1 ( echo [FAIL] flash boot & goto :end )
"%FB%" flash init_boot "%IMG%\init_boot.img"
if errorlevel 1 ( echo [FAIL] flash init_boot & goto :end )

echo.
echo [OK] rollback done, rebooting ...
"%FB%" reboot

:end
echo.
pause
endlocal
