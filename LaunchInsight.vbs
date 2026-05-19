Option Explicit

Dim fso, sh, projectDir, pythonwPath, cmd
Set fso = CreateObject("Scripting.FileSystemObject")
Set sh = CreateObject("WScript.Shell")

projectDir = fso.GetParentFolderName(WScript.ScriptFullName)
pythonwPath = projectDir & "\.venv\Scripts\pythonw.exe"

If Not fso.FileExists(pythonwPath) Then
    MsgBox "未找到虚拟环境运行器：" & vbCrLf & pythonwPath & vbCrLf & vbCrLf & "请先安装依赖后再启动。", vbExclamation, "Insight 启动失败"
    WScript.Quit 1
End If

sh.CurrentDirectory = projectDir
cmd = Chr(34) & pythonwPath & Chr(34) & " -m src.app.main"
sh.Run cmd, 0, False
