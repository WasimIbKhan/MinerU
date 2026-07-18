' Launch start-mineru-api.bat with a hidden console window.
' Put a shortcut to this file in shell:startup to auto-run on login.
Set WshShell = CreateObject("WScript.Shell")
WshShell.Run """C:\Users\User\Documents\GitHub\MinerU\start-mineru-api.bat""", 0, False
