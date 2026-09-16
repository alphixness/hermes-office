' launch-office.vbs -- start the Hermes Office standalone window (ASCII only; safe for WSH)
Option Explicit
Dim fso, sh, here, pyw, script, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh  = CreateObject("WScript.Shell")

here   = fso.GetParentFolderName(WScript.ScriptFullName)
pyw    = fso.BuildPath(here, ".venv\Scripts\pythonw.exe")
script = fso.BuildPath(here, "hermes_office_app.py")

sh.CurrentDirectory = here

If Not fso.FileExists(pyw) Then
  MsgBox "Missing python env: " & pyw & vbCrLf & vbCrLf & _
         "Run once inside hermes-office:" & vbCrLf & _
         "  uv venv .venv" & vbCrLf & _
         "  uv pip install --python .venv\Scripts\python.exe pywebview pythonnet", 48, "Hermes Office"
  WScript.Quit 1
End If

cmd = """" & pyw & """ """ & script & """"
sh.Run cmd, 1, False        ' ⚠️ 必须是 1（正常显示）：用 0=隐藏 会把 pythonw 创建的 GUI 窗口一起隐藏，表现为"进程在跑但看不到窗口"
WScript.Quit 0
