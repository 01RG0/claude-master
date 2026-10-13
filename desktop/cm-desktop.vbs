Set WshShell = CreateObject("WScript.Shell")
WshShell.CurrentDirectory = "D:\\pRoG\\claude-master"
WshShell.Run "pythonw -m desktop.tray", 0, False
