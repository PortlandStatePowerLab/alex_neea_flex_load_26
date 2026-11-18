Attribute VB_Name = "Module4"
Option Explicit

Private OCHRE_LogPath As String
Private OCHRE_DonePath As String
Private OCHRE_NextPoll As Date
Private OCHRE_IsRunning As Boolean
Private OCHRE_PollScheduled As Boolean
Private OCHRE_CloseFormTime As Date
Private OCHRE_CloseFormScheduled As Boolean
Private OCHRE_PreviousInteractive As Boolean
Private OCHRE_ProcessId As Long
Private OCHRE_LastDisplayedLine As String
Private Const OCHRE_MIN_PYTHON_MAJOR As Long = 3
Private Const OCHRE_MIN_PYTHON_MINOR As Long = 9
Private Const OCHRE_MAX_PYTHON_MAJOR As Long = 3
Private Const OCHRE_MAX_PYTHON_MINOR As Long = 12
Private Const OCHRE_ENVIRONMENT_VERSION As String = "1.0"
Private OCHRE_LastLogLineCount As Long
Private OCHRE_BatchPath As String


Public Sub RunOCHRE()

    Dim wsCalc As Worksheet
    Dim fso As Object
    Dim shell As Object
    Dim workbookFolder As String
    Dim projectPath As String
    Dim scriptPath As String
    Dim venvPath As String
    Dim basePythonPath As String
    Dim pythonPath As String
    Dim pythonVersion As String
    Dim OCHRE_BatchPath As String
    Dim runId As String
    Dim f As Integer
    Dim batchOpen As Boolean
    Dim requirementsPath As String
    Dim venvWasCreated As Boolean
    Dim rebuildVenv As Boolean
    Dim launchErrorNumber As Long
    Dim launchErrorDescription As String
    Dim venvCommand As String
    Dim venvLog As String
    Dim venvResult As Long
    Dim environmentVersionPath As String

    On Error GoTo LaunchFailed
    
    ' ------------------------------------------------------------
    ' Make sure another simulation isn't already running.
    ' ------------------------------------------------------------

    If OCHRE_IsRunning Then
        MsgBox "An HPWH simulation is already running.", _
               vbExclamation, "HPWH launcher"
        Exit Sub
    End If

    Set wsCalc = ThisWorkbook.Worksheets("Calculator")

    ' ------------------------------------------------------------
    ' Check calculator inputs.
    ' ------------------------------------------------------------

    If Not RequiredCalculatorInputsArePresent(wsCalc) Then
        MsgBox "Please fill out all required fields." & vbCrLf & _
               "All orange cells should be filled.", _
               vbExclamation, "HPWH launcher"
        Exit Sub
    End If

    ' ------------------------------------------------------------
    ' Determine project location.
    ' ------------------------------------------------------------

    projectPath = ThisWorkbook.Path
    
    If Len(projectPath) = 0 Then
        MsgBox "Save the workbook before running OCHRE.", _
               vbExclamation, "HPWH launcher"
        Exit Sub
    End If

    Set fso = CreateObject("Scripting.FileSystemObject")
    
    Set shell = CreateObject("WScript.Shell")

    scriptPath = projectPath & "\main\hpwh_reg_excel_main.py"
    venvPath = projectPath & "\.venv-hpwh"
    pythonPath = venvPath & "\Scripts\python.exe"
    requirementsPath = projectPath & "\requirements.txt"
    environmentVersionPath = venvPath & "\.ochre_environment_version"

    ' ------------------------------------------------------------
    ' Check that the Python script exists.
    ' ------------------------------------------------------------

    If Dir$(scriptPath) = vbNullString Then

        MsgBox "Cannot find the Python script:" & vbCrLf & _
               scriptPath, _
               vbCritical, "HPWH launcher"

        Exit Sub

    End If
    
    ' ------------------------------------------------------------
    ' Check/create the Python virtual environment.
    ' ------------------------------------------------------------
    
    venvWasCreated = False
    rebuildVenv = False
    
    ' ------------------------------------------------------------
    ' Determine whether the existing environment can be reused.
    ' ------------------------------------------------------------
    
    If Dir$(pythonPath) <> vbNullString Then
    
        If Not OCHREEnvironmentVersionMatches( _
                environmentVersionPath) Then
    
            rebuildVenv = True
    
        End If
    
    End If
    
    If rebuildVenv Then

        MsgBox _
            "The OCHRE Python environment needs to be updated." & _
            vbCrLf & vbCrLf & _
            "Excel will rebuild it automatically.", _
            vbInformation, _
            "HPWH launcher"
    
        If Not DeleteOCHREEnvironment(venvPath) Then
    
            MsgBox _
                "The old OCHRE Python environment could not be removed." & _
                vbCrLf & vbCrLf & _
                "Please close any programs using Python and try again." & _
                vbCrLf & vbCrLf & _
                "Environment:" & vbCrLf & _
                venvPath, _
                vbCritical, _
                "HPWH launcher"
    
            Exit Sub
    
        End If
    
    End If
    
    ' ------------------------------------------------------------
    ' If the virtual environment already exists, verify the
    ' Python version inside it before using it.
    ' ------------------------------------------------------------
    
    If Dir$(pythonPath) <> vbNullString Then
    
        If Not GetPythonVersion( _
                pythonPath, _
                pythonVersion) Then
    
            MsgBox _
                "The existing OCHRE Python environment could not be checked." & _
                vbCrLf & vbCrLf & _
                "Python executable:" & vbCrLf & _
                pythonPath & _
                vbCrLf & vbCrLf & _
                "Please delete the .venv-hpwh folder and run OCHRE again.", _
                vbCritical, _
                "HPWH launcher"
    
            Exit Sub
    
        End If
    
        If Not IsOCHREPythonVersionCompatible(pythonVersion) Then
    
            MsgBox _
                "The existing OCHRE Python environment is not compatible." & _
                vbCrLf & vbCrLf & _
                "Installed version: Python " & pythonVersion & vbCrLf & _
                "Required version: Python >=3.9 and <3.13" & _
                vbCrLf & vbCrLf & _
                "Please delete the .venv-hpwh folder and run OCHRE again.", _
                vbCritical, _
                "HPWH launcher"
    
            Exit Sub
    
        End If
    
    Else
    
        ' --------------------------------------------------------
        ' No virtual environment exists.
        '
        ' Find a compatible system Python installation.
        ' --------------------------------------------------------
    
        If Not FindCompatiblePython( _
                basePythonPath, _
                pythonVersion) Then
    
            MsgBox _
                "A compatible Python installation could not be found." & _
                vbCrLf & vbCrLf & _
                "OCHRE requires Python >=3.9 and <3.13." & _
                vbCrLf & vbCrLf & _
                "Please install Python 3.9, 3.10, 3.11, or 3.12 " & _
                "and try again.", _
                vbCritical, _
                "HPWH launcher"
    
            Exit Sub
    
        End If
    
        ' --------------------------------------------------------
        ' Create the project-local virtual environment.
        ' --------------------------------------------------------
        
        venvLog = Environ$("TEMP") & _
                  "\hpwh_venv_create_" & _
                  Format$(Now, "yyyymmdd_hhnnss") & ".txt"
        
        venvCommand = Q(basePythonPath) & _
                      " -m venv " & _
                      Q(venvPath)
        
        venvResult = shell.Run( _
            venvCommand, _
            0, _
            True)
        
        If venvResult <> 0 Then
        
            MsgBox _
                "Python could not create the virtual environment." & _
                vbCrLf & vbCrLf & _
                "Python version: " & pythonVersion & _
                vbCrLf & _
                "Python location:" & vbCrLf & _
                basePythonPath & _
                vbCrLf & vbCrLf & _
                "Venv location:" & vbCrLf & _
                venvPath & _
                vbCrLf & vbCrLf & _
                "Exit code: " & venvResult, _
                vbCritical, _
                "HPWH launcher"
        
            Exit Sub
        
        End If
    
        ' --------------------------------------------------------
        ' Verify that the venv was actually created.
        ' --------------------------------------------------------
    
        If Dir$(pythonPath) = vbNullString Then
    
            MsgBox _
                "Python reported that the virtual environment was " & _
                "created, but python.exe could not be found." & _
                vbCrLf & vbCrLf & _
                "Expected location:" & vbCrLf & _
                pythonPath & _
                vbCrLf & vbCrLf & _
                "Check the venv creation log:" & vbCrLf & _
                venvLog, _
                vbCritical, _
                "HPWH launcher"
    
            Exit Sub
    
        End If
    
        ' --------------------------------------------------------
        ' Verify the Python version inside the newly-created venv.
        ' --------------------------------------------------------
    
        If Not GetPythonVersion( _
                pythonPath, _
                pythonVersion) Then
    
            MsgBox _
                "The virtual environment was created, but its " & _
                "Python installation could not be verified." & _
                vbCrLf & vbCrLf & _
                "Python executable:" & vbCrLf & _
                pythonPath, _
                vbCritical, _
                "HPWH launcher"
    
            Exit Sub
    
        End If
    
        If Not IsOCHREPythonVersionCompatible(pythonVersion) Then
    
            MsgBox _
                "The newly-created virtual environment contains " & _
                "an incompatible Python version." & _
                vbCrLf & vbCrLf & _
                "Installed version: Python " & pythonVersion & vbCrLf & _
                "Required version: Python >=3.9 and <3.13", _
                vbCritical, _
                "HPWH launcher"
    
            Exit Sub
    
        End If
    
        venvWasCreated = True
    
    End If
    
    ' ------------------------------------------------------------
    ' Install Python dependencies when the venv is first created.
    ' ------------------------------------------------------------

    If venvWasCreated Then

        If Dir$(requirementsPath) = vbNullString Then
    
            MsgBox "Cannot find requirements.txt:" & vbCrLf & _
                   requirementsPath, _
                   vbCritical, "HPWH launcher"
    
            Exit Sub
    
        End If
    
        MsgBox "Installing Python dependencies." & vbCrLf & _
               "This may take several minutes the first time.", _
               vbInformation, "HPWH launcher"
    
        If Not InstallPythonRequirements( _
                pythonPath, _
                requirementsPath) Then
    
            MsgBox "Python dependencies could not be installed." & _
                   vbCrLf & vbCrLf & _
                   "Check your internet connection and make sure " & _
                   "Python/pip are working correctly.", _
                   vbCritical, "HPWH launcher"
    
            Exit Sub
    
        End If
    
        ' --------------------------------------------------------
        ' Mark the environment as successfully initialized.
        ' --------------------------------------------------------
    
        If Not WriteOCHREEnvironmentVersion( _
                environmentVersionPath) Then
    
            MsgBox _
                "The Python environment was installed successfully, " & _
                "but Excel could not save its environment version." & _
                vbCrLf & vbCrLf & _
                "Expected marker location:" & vbCrLf & _
                environmentVersionPath, _
                vbCritical, _
                "HPWH launcher"
    
            Exit Sub
    
        End If
    
    End If

    ' ------------------------------------------------------------
    ' Create unique files for this run.
    ' ------------------------------------------------------------

    DeletePreviousOCHRETempFiles
    
    runId = Format$(Now, "yyyymmdd_hhnnss")

    OCHRE_BatchPath = Environ$("TEMP") & _
        "\run_hpwh_regulation_" & runId & ".cmd"

    OCHRE_LogPath = Environ$("TEMP") & _
                    "\hpwh_regulation_log_" & runId & ".txt"

    OCHRE_DonePath = Environ$("TEMP") & _
                     "\hpwh_regulation_done_" & runId & ".txt"

    ' A unique done file avoids treating a prior run as complete.
    If Dir$(OCHRE_DonePath) <> vbNullString Then
        Kill OCHRE_DonePath
    End If

    If Dir$(OCHRE_LogPath) <> vbNullString Then
        Kill OCHRE_LogPath
    End If

    ' ------------------------------------------------------------
    ' Write the batch file.
    ' ------------------------------------------------------------

    f = FreeFile
    Open OCHRE_BatchPath For Output As #f
    batchOpen = True

    Print #f, "@echo off"
    Print #f, "setlocal"

    Print #f, "> " & Q(OCHRE_LogPath) & _
              " echo [STATUS] Preparing HPWH simulation..."

    Print #f, "cd /d " & Q(projectPath)

    Print #f, ">> " & Q(OCHRE_LogPath) & _
              " echo [STATUS] Running Python simulation..."

    Print #f, Q(pythonPath) & " -u " & Q(scriptPath) & _
          " >> " & Q(OCHRE_LogPath) & " 2>&1"

    Print #f, "set ""OCHRE_EXIT=%ERRORLEVEL%"""

    Print #f, "if ""%OCHRE_EXIT%""==""0"" ("

    Print #f, "    >> " & Q(OCHRE_LogPath) & _
              " echo [STATUS] Simulation completed."

    Print #f, "    > " & Q(OCHRE_DonePath) & _
              " echo COMPLETE"

    Print #f, ") else ("

    Print #f, "    >> " & Q(OCHRE_LogPath) & _
              " echo [FAILED] Python exited with code %OCHRE_EXIT%."

    Print #f, "    > " & Q(OCHRE_DonePath) & _
              " echo FAILED"

    Print #f, ")"

    Print #f, "endlocal"

    Close #f
    batchOpen = False
    
    ' ------------------------------------------------------------
    ' Verify that the batch file was actually created.
    ' ------------------------------------------------------------
    
    If Dir$(OCHRE_BatchPath) = vbNullString Then
    
        Err.Raise vbObjectError + 1002, _
                  "RunOCHRE", _
                  "The batch file could not be found after it was created." & _
                  vbCrLf & vbCrLf & _
                  "Expected location:" & vbCrLf & _
                  OCHRE_BatchPath
    
    End If
    
    ' ------------------------------------------------------------
    ' Start progress UI.
    ' ------------------------------------------------------------

    OCHRE_PreviousInteractive = Application.Interactive
    OCHRE_ProcessId = 0

    Load frmOCHREProgress
    OCHRE_LastDisplayedLine = vbNullString
    OCHRE_LastLogLineCount = 0

    frmOCHREProgress.txtProgressLog.Text = _
        "Starting HPWH simulation..."

    frmOCHREProgress.Show vbModeless

    ' ------------------------------------------------------------
    ' Start the batch file.
    '
    ' IMPORTANT:
    ' Do not set Application.Interactive = False here.
    ' The progress form needs to remain clickable so that the
    ' user can select Exit OCHRE.
    ' ------------------------------------------------------------

    ' ------------------------------------------------------------
    ' Start the batch file.
    ' ------------------------------------------------------------
    
    Dim commandLine As String
    Dim cmdExe As String
    
    ' Make absolutely sure the batch file exists.
    If Dir$(OCHRE_BatchPath) = vbNullString Then
    
        Err.Raise vbObjectError + 1002, _
                  "RunOCHRE", _
                  "The batch file does not exist:" & _
                  vbCrLf & vbCrLf & OCHRE_BatchPath
    
    End If
    
    cmdExe = Environ$("COMSPEC")
    
    If Len(cmdExe) = 0 Then
    
        Err.Raise vbObjectError + 1003, _
                  "RunOCHRE", _
                  "Windows COMSPEC environment variable could not be found."
    
    End If
    
    commandLine = Q(cmdExe) & _
                  " /d /c call " & _
                  Q(OCHRE_BatchPath)
    
    ' ------------------------------------------------------------
    ' Start cmd.exe using VBA's native Shell function.
    '
    ' IMPORTANT:
    ' VBA.Shell is used explicitly because "shell" is also the
    ' name of our WScript.Shell object.
    ' ------------------------------------------------------------
    
    OCHRE_ProcessId = VBA.shell(commandLine, vbHide)
    
    If OCHRE_ProcessId <= 0 Then
    
        Err.Raise vbObjectError + 1000, _
                  "RunOCHRE", _
                  "Windows did not return a valid process ID."
    
    End If
    
    ' The process successfully started.
    OCHRE_IsRunning = True
    
    ScheduleOCHREProgressCheck

    Exit Sub

LaunchFailed:

    ' ------------------------------------------------------------
    ' Save the original error BEFORE doing any cleanup.
    ' Cleanup operations can overwrite Err.Number/Err.Description.
    ' ------------------------------------------------------------

    launchErrorNumber = Err.Number
    launchErrorDescription = Err.Description

    If batchOpen Then
        Close #f
    End If

    OCHRE_IsRunning = False
    OCHRE_ProcessId = 0

    CancelOCHREProgressCheck
    CloseOCHREProgressForm
    RestoreExcelInterface
    

    On Error Resume Next

    MsgBox "Could not launch the HPWH simulation." & _
           vbCrLf & vbCrLf & _
           "Error " & launchErrorNumber & ": " & _
           launchErrorDescription, _
           vbCritical, "HPWH launcher"
           
End Sub


Public Sub ScheduleOCHREProgressCheck()

    If Not OCHRE_IsRunning Or OCHRE_PollScheduled Then Exit Sub

    OCHRE_NextPoll = Now + TimeSerial(0, 0, 1)

    Application.OnTime _
        EarliestTime:=OCHRE_NextPoll, _
        Procedure:="PollOCHREProgress", _
        Schedule:=True

    OCHRE_PollScheduled = True

End Sub


Public Sub PollOCHREProgress()

    Dim logText As String
    Dim doneText As String

    OCHRE_PollScheduled = False

    If Not OCHRE_IsRunning Then Exit Sub

    On Error GoTo PollFailed

    ' ------------------------------------------------------------
    ' Update progress display from the latest log line.
    ' ------------------------------------------------------------
    
    If Dir$(OCHRE_LogPath) <> vbNullString Then

        logText = ReadTextFile(OCHRE_LogPath)
    
        If Len(logText) > 0 Then
    
            Dim logLines() As String
            Dim latestLine As String
            Dim i As Long
    
            ' Normalize line endings.
            logText = Replace(logText, vbCrLf, vbLf)
            logText = Replace(logText, vbCr, vbLf)
    
            logLines = Split(logText, vbLf)
    
            ' Find the last non-empty line.
            latestLine = vbNullString
    
            If OCHRE_LastLogLineCount > UBound(logLines) Then
                OCHRE_LastLogLineCount = 0
            End If
            
            For i = OCHRE_LastLogLineCount To UBound(logLines)
            
                latestLine = Trim$(logLines(i))
            
                If Len(latestLine) > 0 Then
            
                    frmOCHREProgress.txtProgressLog.Text = _
                        frmOCHREProgress.txtProgressLog.Text & _
                        latestLine & vbCrLf
            
                    frmOCHREProgress.txtProgressLog.SelStart = _
                        Len(frmOCHREProgress.txtProgressLog.Text)
            
                    frmOCHREProgress.txtProgressLog.Text = latestLine
            
                    If latestLine = "[STATUS] Simulation completed." Then

                        FinishOCHRERun "COMPLETE"
                        Exit Sub
                    
                    ElseIf Left$(latestLine, 8) = "[FAILED]" Then
                    
                        FinishOCHRERun "FAILED"
                        Exit Sub
                    
                    End If
            
                End If
            
            Next i
            
            OCHRE_LastLogLineCount = UBound(logLines) + 1
    
            If Len(latestLine) > 0 Then
            
                ' This exact line is written by the batch file only after
                ' Python has exited successfully.
                If latestLine = "[STATUS] Simulation completed." Then
            
                    FinishOCHRERun "COMPLETE"
                    Exit Sub
            
                End If
            
                If latestLine <> OCHRE_LastDisplayedLine Then
                End If
            End If
        End If
    
    End If

    ' ------------------------------------------------------------
    ' Check whether Python has finished.
    ' ------------------------------------------------------------

    If Dir$(OCHRE_DonePath) <> vbNullString Then

        doneText = UCase$(Trim$(ReadTextFile(OCHRE_DonePath)))
    
        Select Case doneText

            Case "COMPLETE", "FAILED", "CANCELLED"
        
                FinishOCHRERun doneText
    
            Case Else
    
                ' Ignore an unexpected status and keep polling.
                ScheduleOCHREProgressCheck
    
        End Select
    
        Exit Sub
    
    End If

    ScheduleOCHREProgressCheck

    Exit Sub


Dim pollErrorNumber As Long
Dim pollErrorDescription As String

PollFailed:

    pollErrorNumber = Err.Number
    pollErrorDescription = Err.Description

    OCHRE_IsRunning = False
    OCHRE_ProcessId = 0

    CancelOCHREProgressCheck
    RestoreExcelInterface

    CloseOCHREProgressForm
    
    DoEvents

    MsgBox "The OCHRE progress monitor encountered an error." & _
           vbCrLf & vbCrLf & _
           "Error " & pollErrorNumber & ": " & _
           pollErrorDescription, _
           vbCritical, "HPWH launcher"
           
End Sub



Public Sub ExitOCHRE()

    Dim shell As Object
    Dim result As Long
    Dim f As Integer
    Dim currentStatus As String
    Dim exitErrorNumber As Long
    Dim exitErrorDescription As String
    Dim projectPath As String
    Dim pythonPath As String
    Dim cleanupScriptPath As String
    Dim cleanupResult As Long
    Dim cleanupMessage As String

    If Not OCHRE_IsRunning Then

        MsgBox "There is no OCHRE simulation currently running.", _
               vbInformation, "HPWH launcher"

        Exit Sub

    End If

    If MsgBox( _
        "Are you sure you want to stop the current OCHRE simulation?", _
        vbYesNo + vbQuestion, _
        "Exit OCHRE") <> vbYes Then
        
        Exit Sub

    End If

    On Error GoTo ExitFailed

    ' ------------------------------------------------------------
    ' Immediately show that the process is being stopped.
    ' ------------------------------------------------------------

    frmOCHREProgress.txtProgressLog.Text = _
        "Stopping OCHRE..." & vbCrLf & _
        "Please wait."

    DoEvents

    ' Stop progress polling while the process is being terminated.
    CancelOCHREProgressCheck

    ' ------------------------------------------------------------
    ' Record cancellation attempt in the log.
    ' ------------------------------------------------------------

    AppendToOCHRELog "[STATUS] User requested OCHRE cancellation."
    AppendToOCHRELog "[STATUS] Stopping OCHRE..."

    ' ------------------------------------------------------------
    ' Terminate cmd.exe and all child processes.
    ' ------------------------------------------------------------

    If OCHRE_ProcessId > 0 Then

        Set shell = CreateObject("WScript.Shell")

        result = shell.Run( _
            "taskkill /PID " & CStr(OCHRE_ProcessId) & _
            " /T /F", _
            0, _
            True)

    Else

        result = 1

    End If

    ' ------------------------------------------------------------
    ' Determine whether the process was actually stopped.
    ' ------------------------------------------------------------

    If result = 0 Then

        OCHRE_IsRunning = False
        OCHRE_ProcessId = 0
    
        ' ------------------------------------------------------------
        ' Run HPWH_D2.py after OCHRE has been stopped.
        ' ------------------------------------------------------------
    
        frmOCHREProgress.txtProgressLog.Text = _
            "OCHRE stopped." & vbCrLf & _
            "Deleting temporary building files..."
    
        DoEvents
    
        projectPath = ThisWorkbook.Path
        pythonPath = projectPath & "\.venv-hpwh\Scripts\python.exe"
        cleanupScriptPath = projectPath & "\HPWH\HPWH_D2.py"
    
        If Dir$(pythonPath) = vbNullString Then
    
            cleanupMessage = _
                "The cleanup could not run because Python was not found:" & _
                vbCrLf & vbCrLf & pythonPath
    
        ElseIf Dir$(cleanupScriptPath) = vbNullString Then
    
            cleanupMessage = _
                "The cleanup Python file was not found:" & _
                vbCrLf & vbCrLf & cleanupScriptPath
    
        Else
    
            AppendToOCHRELog _
                "[STATUS] Running HPWH_D2.py cleanup..."
    
            cleanupResult = shell.Run( _
                Q(pythonPath) & " -u " & Q(cleanupScriptPath), _
                0, _
                True)
    
            If cleanupResult = 0 Then
    
                AppendToOCHRELog _
                    "[STATUS] Temporary building-file cleanup completed."
    
            Else
    
                cleanupMessage = _
                    "OCHRE was stopped, but HPWH_D2.py failed." & _
                    vbCrLf & vbCrLf & _
                    "Python exit code: " & CStr(cleanupResult)
    
                AppendToOCHRELog _
                    "[FAILED] HPWH_D2.py exited with code " & _
                    CStr(cleanupResult) & "."
    
            End If
    
        End If
    
        CloseOCHREProgressForm "CANCELLED"
    
        If Len(cleanupMessage) > 0 Then
            MsgBox cleanupMessage, _
                   vbExclamation, _
                   "HPWH cleanup"
        End If
    
        Exit Sub
    
    End If

    ' ------------------------------------------------------------
    ' taskkill may fail if the process finished between the time
    ' the user clicked Exit and the time taskkill ran.
    '
    ' Check the existing completion status before reporting failure.
    ' ------------------------------------------------------------

    If Dir$(OCHRE_DonePath) <> vbNullString Then

        currentStatus = _
            UCase$(Trim$(ReadTextFile(OCHRE_DonePath)))

        If currentStatus = "COMPLETE" Or _
           currentStatus = "FAILED" Then

            FinishOCHRERun currentStatus
            Exit Sub

        End If

    End If

    ' ------------------------------------------------------------
    ' We couldn't verify that the process was stopped.
    ' ------------------------------------------------------------

    Err.Raise vbObjectError + 1001, _
              "ExitOCHRE", _
              "Windows could not terminate the OCHRE process."

    Exit Sub

ExitFailed:

    exitErrorNumber = Err.Number
    exitErrorDescription = Err.Description

    OCHRE_IsRunning = False
    OCHRE_ProcessId = 0

    On Error Resume Next
    Application.Interactive = True
    CloseOCHREProgressForm
    
    On Error GoTo 0

    MsgBox "OCHRE could not be stopped cleanly." & _
           vbCrLf & vbCrLf & _
           "Error " & exitErrorNumber & ": " & _
           exitErrorDescription, _
           vbCritical, "HPWH launcher"

End Sub


Private Sub FinishOCHRERun(ByVal status As String)

    Dim finalStatus As String

    CancelOCHREProgressCheck

    OCHRE_IsRunning = False
    OCHRE_ProcessId = 0

    finalStatus = UCase$(Trim$(status))

    Select Case finalStatus

        Case "COMPLETE"
            frmOCHREProgress.txtProgressLog.Text = _
                "[STATUS] Simulation completed."

        Case "FAILED"
            frmOCHREProgress.txtProgressLog.Text = _
                "[FAILED] Simulation failed."

        Case "CANCELLED"
            frmOCHREProgress.txtProgressLog.Text = _
                "[CANCELLED] Simulation cancelled."

        Case Else
            Exit Sub

    End Select

    CloseOCHREProgressForm finalStatus

End Sub


Private Sub AppendToOCHRELog(ByVal message As String)

    Dim f As Integer

    If Len(OCHRE_LogPath) = 0 Then Exit Sub

    On Error GoTo LogFailed

    f = FreeFile

    Open OCHRE_LogPath For Append Access Write As #f

    Print #f, message

    Close #f

    Exit Sub

LogFailed:

    On Error Resume Next

    If f <> 0 Then Close #f

    On Error GoTo 0

End Sub


Public Sub ResetOCHREInterface()

    CancelOCHREProgressCheck

    OCHRE_IsRunning = False
    OCHRE_ProcessId = 0

    Application.Interactive = True

    CloseOCHREProgressForm
    
    DoEvents

End Sub


Private Sub CancelOCHREProgressCheck()

    If Not OCHRE_PollScheduled Then Exit Sub

    On Error Resume Next

    Application.OnTime _
        EarliestTime:=OCHRE_NextPoll, _
        Procedure:="PollOCHREProgress", _
        Schedule:=False

    On Error GoTo 0

    OCHRE_PollScheduled = False

End Sub


Private Function RequiredCalculatorInputsArePresent( _
    ByVal ws As Worksheet) As Boolean

    RequiredCalculatorInputsArePresent = _
        HasCellValue(ws.Range("K34")) And _
        HasCellValue(ws.Range("K36")) And _
        HasCellValue(ws.Range("K38")) And _
        HasCellValue(ws.Range("N31")) And _
        HasCellValue(ws.Range("N32")) And _
        HasCellValue(ws.Range("N34")) And _
        HasCellValue(ws.Range("N35"))

End Function


Private Function HasCellValue(ByVal target As Range) As Boolean

    If IsError(target.Value2) Then Exit Function

    HasCellValue = _
        (Len(Trim$(CStr(target.Value2))) > 0)

End Function


Private Function ReadTextFile(ByVal filePath As String) As String

    Dim f As Integer

    f = FreeFile

    Open filePath For Input Access Read Shared As #f

    ReadTextFile = Input$(LOF(f), f)

    Close #f

End Function


Private Function Q(ByVal value As String) As String

    Q = Chr$(34) & value & Chr$(34)

End Function



Private Function InstallPythonRequirements( _
    ByVal pythonPath As String, _
    ByVal requirementsPath As String) As Boolean

    Dim shell As Object
    Dim result As Long
    Dim command As String

    On Error GoTo InstallFailed

    Set shell = CreateObject("WScript.Shell")

    command = Q(pythonPath) & _
              " -m pip install -r " & _
              Q(requirementsPath) & _
              " --disable-pip-version-check"

    result = shell.Run( _
        command, _
        1, _
        True)

    InstallPythonRequirements = (result = 0)

    Exit Function

InstallFailed:

    InstallPythonRequirements = False

End Function

Private Sub RestoreExcelInterface()

    On Error Resume Next

    Application.Interactive = True
    Application.EnableEvents = True
    Application.ScreenUpdating = True
    Application.Cursor = xlDefault

    On Error GoTo 0

End Sub

Private Function FindCompatiblePython( _
    ByRef pythonPath As String, _
    ByRef versionText As String) As Boolean

    Dim shell As Object
    Dim exec As Object
    Dim command As String
    Dim output As String
    Dim lines() As String
    Dim candidatePath As String
    Dim candidateVersion As String
    Dim testVersions As Variant
    Dim i As Long

    FindCompatiblePython = False
    pythonPath = vbNullString
    versionText = vbNullString

    On Error GoTo PythonNotFound

    Set shell = CreateObject("WScript.Shell")

    ' ------------------------------------------------------------
    ' Try the Python Launcher first.
    '
    ' Explicitly test supported Python versions rather than
    ' asking "py" to choose one automatically.
    ' ------------------------------------------------------------

    testVersions = Array("3.12", "3.11", "3.10", "3.9")

    For i = LBound(testVersions) To UBound(testVersions)

        command = Environ$("COMSPEC") & _
                  " /d /c py -" & testVersions(i) & _
                  " -c ""import sys; " & _
                  "print(sys.executable); " & _
                  "print(sys.version_info.major); " & _
                  "print(sys.version_info.minor)"""

        Set exec = shell.exec(command)

        If exec.ExitCode = 0 Then

            output = exec.StdOut.ReadAll

            output = Replace(output, vbCrLf, vbLf)
            output = Replace(output, vbCr, vbLf)

            lines = Split(output, vbLf)

            If UBound(lines) >= 2 Then

                candidatePath = Trim$(lines(0))

                If Len(candidatePath) > 0 Then

                    If Dir$(candidatePath) <> vbNullString Then

                        ' Never accept Microsoft Store Python.
                        If InStr(1, candidatePath, _
                                 "\WindowsApps\", _
                                 vbTextCompare) = 0 Then

                            candidateVersion = _
                                Trim$(lines(1)) & "." & _
                                Trim$(lines(2))

                            If IsOCHREPythonVersionCompatible( _
                                    candidateVersion) Then

                                pythonPath = candidatePath
                                versionText = candidateVersion

                                FindCompatiblePython = True

                                Exit Function

                            End If

                        End If

                    End If

                End If

            End If

        End If

    Next i

    ' ------------------------------------------------------------
    ' Second choice:
    ' Look for python.exe on PATH.
    ' ------------------------------------------------------------

    command = Environ$("COMSPEC") & _
              " /d /c python -c ""import sys; " & _
              "print(sys.executable); " & _
              "print(sys.version_info.major); " & _
              "print(sys.version_info.minor)"""

    Set exec = shell.exec(command)

    If exec.ExitCode = 0 Then

        output = exec.StdOut.ReadAll

        output = Replace(output, vbCrLf, vbLf)
        output = Replace(output, vbCr, vbLf)

        lines = Split(output, vbLf)

        If UBound(lines) >= 2 Then

            candidatePath = Trim$(lines(0))

            If Len(candidatePath) > 0 Then

                If Dir$(candidatePath) <> vbNullString Then

                    ' Never accept Microsoft Store Python.
                    If InStr(1, candidatePath, _
                             "\WindowsApps\", _
                             vbTextCompare) = 0 Then

                        candidateVersion = _
                            Trim$(lines(1)) & "." & _
                            Trim$(lines(2))

                        If IsOCHREPythonVersionCompatible( _
                                candidateVersion) Then

                            pythonPath = candidatePath
                            versionText = candidateVersion

                            FindCompatiblePython = True

                            Exit Function

                        End If

                    End If

                End If

            End If

        End If

    End If

    Exit Function

PythonNotFound:

    FindCompatiblePython = False
    pythonPath = vbNullString
    versionText = vbNullString

End Function



Private Function GetPythonVersion( _
    ByVal pythonPath As String, _
    ByRef versionText As String) As Boolean

    Dim shell As Object
    Dim exec As Object
    Dim command As String
    Dim output As String

    GetPythonVersion = False
    versionText = vbNullString

    On Error GoTo VersionFailed

    If Dir$(pythonPath) = vbNullString Then
        Exit Function
    End If

    Set shell = CreateObject("WScript.Shell")

    command = Q(pythonPath) & _
              " -c ""import sys; print(str(sys.version_info.major) + '.' + str(sys.version_info.minor))"""

    Set exec = shell.exec(command)

    If exec.ExitCode <> 0 Then
        Exit Function
    End If

    output = exec.StdOut.ReadAll

    output = Replace(output, vbCrLf, vbNullString)
    output = Replace(output, vbCr, vbNullString)
    output = Replace(output, vbLf, vbNullString)

    versionText = Trim$(output)

    If Len(versionText) = 0 Then
        Exit Function
    End If

    GetPythonVersion = True

    Exit Function

VersionFailed:

    GetPythonVersion = False
    versionText = vbNullString

End Function



Private Function IsOCHREPythonVersionCompatible( _
    ByVal versionText As String) As Boolean

    Dim parts() As String
    Dim majorVersion As Long
    Dim minorVersion As Long

    IsOCHREPythonVersionCompatible = False

    On Error GoTo VersionInvalid

    parts = Split(versionText, ".")

    If UBound(parts) < 1 Then Exit Function

    majorVersion = CLng(parts(0))
    minorVersion = CLng(parts(1))

    ' ------------------------------------------------------------
    ' OCHRE requires:
    '
    ' Python >= 3.9
    ' Python <= 3.12
    ' ------------------------------------------------------------

    If majorVersion < OCHRE_MIN_PYTHON_MAJOR Then Exit Function
    If majorVersion > OCHRE_MAX_PYTHON_MAJOR Then Exit Function

    If majorVersion = OCHRE_MIN_PYTHON_MAJOR Then
        If minorVersion < OCHRE_MIN_PYTHON_MINOR Then Exit Function
    End If

    If majorVersion = OCHRE_MAX_PYTHON_MAJOR Then
        If minorVersion > OCHRE_MAX_PYTHON_MINOR Then Exit Function
    End If

    IsOCHREPythonVersionCompatible = True

    Exit Function

VersionInvalid:

    IsOCHREPythonVersionCompatible = False

End Function


Public Sub CloseOCHREProgressForm( _
    Optional ByVal finalStatus As String = vbNullString)

    OCHRE_CloseFormScheduled = False

    ' ------------------------------------------------------------
    ' Close the progress form.
    ' CloseForm sets AllowFormClose and unloads the form itself.
    ' ------------------------------------------------------------

    On Error Resume Next

    frmOCHREProgress.CloseForm

    On Error GoTo 0

    RestoreExcelInterface

    DoEvents

    ' ------------------------------------------------------------
    ' Show the final result after the progress form is gone.
    ' ------------------------------------------------------------

    Select Case UCase$(Trim$(finalStatus))

        Case "COMPLETE"

            MsgBox "HPWH simulation completed successfully.", _
                   vbInformation, _
                   "HPWH launcher"

        Case "FAILED"

            MsgBox "HPWH simulation failed.", _
                   vbCritical, _
                   "HPWH launcher"

        Case "CANCELLED"

            MsgBox "HPWH simulation was cancelled.", _
                   vbInformation, _
                   "HPWH launcher"

    End Select

End Sub

Private Function OCHREEnvironmentVersionMatches( _
    ByVal environmentVersionPath As String) As Boolean

    Dim installedVersion As String

    OCHREEnvironmentVersionMatches = False

    If Len(environmentVersionPath) = 0 Then
        Exit Function
    End If

    If Dir$(environmentVersionPath) = vbNullString Then
        Exit Function
    End If

    On Error GoTo VersionCheckFailed

    installedVersion = _
        ReadTextFile(environmentVersionPath)

    ' Remove line-ending characters written by Print #.
    installedVersion = Replace(installedVersion, vbCr, vbNullString)
    installedVersion = Replace(installedVersion, vbLf, vbNullString)
    installedVersion = Trim$(installedVersion)

    OCHREEnvironmentVersionMatches = _
        (StrComp( _
            installedVersion, _
            OCHRE_ENVIRONMENT_VERSION, _
            vbBinaryCompare) = 0)

    Exit Function

VersionCheckFailed:

    OCHREEnvironmentVersionMatches = False

End Function



Private Function WriteOCHREEnvironmentVersion( _
    ByVal environmentVersionPath As String) As Boolean

    Dim f As Integer

    WriteOCHREEnvironmentVersion = False

    On Error GoTo WriteFailed

    f = FreeFile

    Open environmentVersionPath For Output As #f

    Print #f, OCHRE_ENVIRONMENT_VERSION

    Close #f
    f = 0

    ' Verify that the file actually exists.
    If Dir$(environmentVersionPath) = vbNullString Then
        Exit Function
    End If

    WriteOCHREEnvironmentVersion = True

    Exit Function

WriteFailed:

    On Error Resume Next

    If f <> 0 Then Close #f

    On Error GoTo 0

End Function


Private Function DeleteOCHREEnvironment( _
    ByVal venvPath As String) As Boolean

    Dim fso As Object

    DeleteOCHREEnvironment = False

    On Error GoTo DeleteFailed

    Set fso = CreateObject("Scripting.FileSystemObject")

    If fso.FolderExists(venvPath) Then

        fso.DeleteFolder _
            venvPath, _
            True

    End If

    DeleteOCHREEnvironment = _
        Not fso.FolderExists(venvPath)

    Exit Function

DeleteFailed:

    DeleteOCHREEnvironment = False

End Function



Private Sub DeletePreviousOCHRETempFiles()

    Dim tempFolder As String

    tempFolder = Environ$("TEMP")

    If Len(tempFolder) = 0 Then Exit Sub

    DeleteTempFilesMatching tempFolder, "run_hpwh_regulation_*.cmd"
    DeleteTempFilesMatching tempFolder, "hpwh_regulation_log_*.txt"
    DeleteTempFilesMatching tempFolder, "hpwh_regulation_done_*.txt"

End Sub


Private Sub DeleteTempFilesMatching( _
    ByVal folderPath As String, _
    ByVal filePattern As String)

    Dim fileName As String

    On Error Resume Next

    fileName = Dir$(folderPath & "\" & filePattern)

    Do While Len(fileName) > 0
        Kill folderPath & "\" & fileName
        fileName = Dir$()
    Loop

    On Error GoTo 0

End Sub
