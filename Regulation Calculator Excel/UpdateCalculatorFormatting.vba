Option Explicit

Public Sub UpdateCalculatorFormatting()

    Dim wsCalc As Worksheet
    Dim wsFormat As Worksheet

    Dim PythonorCF As String

    Set wsCalc = Worksheets("Calculator")
    Set wsFormat = Worksheets("CF Formatting")

    PythonorCF = wsCalc.Range("I12").Value

    '---------------------------------------
    'Clear old inputs
    '---------------------------------------
    wsCalc.Range("H14:M24").Clear

    '---------------------------------------
    'Load CF layout
    '---------------------------------------
    If PythonorCF = "CF" Then
        wsFormat.Range("H14:M24").Copy Destination:=wsCalc.Range("H14:M24")
    End If

End Sub

