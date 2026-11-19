Attribute VB_Name = "Module4"
Public Sub RunOCHRE()
    ' Optional: set this to the full path of a Python 3.12.10 executable.
    Const PYTHON_EXE As String = ""
    Const SCRIPT_RELATIVE_PATH As String = "\Code\main.py"

    Dim scriptPath As String
    Dim pythonPath As String
    Dim pythonCommand As String
    Dim launchCommand As String
    Dim quote As String
    Dim launcher As Object

    On Error GoTo LaunchFailed

    If Len(ThisWorkbook.Path) = 0 Then
        MsgBox "Save the calculator workbook before running OCHRE.", vbExclamation
        Exit Sub
    End If

    scriptPath = ThisWorkbook.Path & SCRIPT_RELATIVE_PATH
    If Len(Dir$(scriptPath)) = 0 Then
        MsgBox "The OCHRE launcher was not found at:" & vbCrLf & scriptPath, vbExclamation
        Exit Sub
    End If

    quote = Chr$(34)
    pythonPath = PYTHON_EXE

    If Len(pythonPath) > 0 Then
        If Len(Dir$(pythonPath)) = 0 Then
            MsgBox "The configured Python executable was not found at:" & _
                   vbCrLf & pythonPath, vbExclamation
            Exit Sub
        End If
        pythonCommand = quote & pythonPath & quote
    Else
        pythonPath = Environ$("LOCALAPPDATA") & "\Programs\Python\Python312\python.exe"
        If Len(Dir$(pythonPath)) > 0 Then
            pythonCommand = quote & pythonPath & quote
        Else
            pythonCommand = "py.exe -3.12"
        End If
    End If

    launchCommand = pythonCommand & " -u " & quote & scriptPath & quote & _
                    " --workbook " & quote & ThisWorkbook.FullName & quote

    Set launcher = CreateObject("WScript.Shell")
    launcher.Run launchCommand, 0, False
    Exit Sub

LaunchFailed:
    MsgBox "Excel could not start the OCHRE launcher." & vbCrLf & _
           Err.Description, vbExclamation
End Sub

