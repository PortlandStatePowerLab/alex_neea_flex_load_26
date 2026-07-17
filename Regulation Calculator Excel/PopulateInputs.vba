Option Explicit

Public Sub PopulateInputs()

    Dim wsCalc As Worksheet
    Dim wsLookup As Worksheet

    Dim SelectedType As String

    Dim LastLookupRow As Long
    Dim LookupRow As Long
    Dim OutputRow As Long

    Set wsCalc = Worksheets("Calculator")
    Set wsLookup = Worksheets("Lookup")

    SelectedType = wsCalc.Range("C4").Value

    '---------------------------------------
    'Clear old inputs
    '---------------------------------------

    wsCalc.Range("C7:E20").ClearContents
    wsCalc.Range("C5").MergeArea.ClearContents
    wsCalc.Range("C5").MergeArea.Value = "Name of Flex Load Under Study"

    OutputRow = 7

    LastLookupRow = wsLookup.Cells(wsLookup.Rows.Count, "C").End(xlUp).Row

    '---------------------------------------
    'Populate new inputs
    '---------------------------------------

    For LookupRow = 4 To LastLookupRow

        If wsLookup.Cells(LookupRow, "C").Value = SelectedType Then

            wsCalc.Cells(OutputRow, "C").Value = _
                wsLookup.Cells(LookupRow, "E").Value

            wsCalc.Cells(OutputRow, "D").Value = _
                wsLookup.Cells(LookupRow, "F").Value

            'Leave Value column blank
            wsCalc.Cells(OutputRow, "E").ClearContents

            OutputRow = OutputRow + 1

        End If

    Next LookupRow
    
    wsCalc.Range("E31:E39").ClearContents

End Sub

