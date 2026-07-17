Option Explicit

Private Const SUPPORTED_VERSION As String = "2"

Sub ImportDevice()

    Dim xmlDoc As Object
    Dim ws As Worksheet
    Dim FileName As Variant
    Dim RootName As String
    Dim Version As String

    FileName = Application.GetOpenFilename( _
        "XML Files (*.xml),*.xml", _
        , "Select Device XML")

    If FileName = False Then Exit Sub

    Set xmlDoc = CreateObject("MSXML2.DOMDocument.6.0")
    xmlDoc.async = False
    xmlDoc.validateOnParse = False

    If Not xmlDoc.Load(FileName) Then
        MsgBox "Unable to load XML file.", vbCritical
        Exit Sub
    End If

    Set ws = Worksheets("Calculator")

    '------------------------------------
    'Check XML Version
    '------------------------------------

    Version = GetXMLValue(xmlDoc, "//Version")

    If Version <> SUPPORTED_VERSION Then
        MsgBox "Unsupported XML version." & vbCrLf & _
               "Expected: " & SUPPORTED_VERSION & vbCrLf & _
               "Found: " & Version, vbCritical
        Exit Sub
    End If

    '------------------------------------
    'Clear previous values
    '------------------------------------

    ws.Range("E7:E15").ClearContents
    ws.Range("E31:E39").ClearContents

    '------------------------------------
    'Determine Device Type
    '------------------------------------
    
    With Worksheets("Calculator")
        .Range("C5").Value = GetXMLValue(xmlDoc, "//DeviceName")
    End With

    RootName = UCase(xmlDoc.DocumentElement.NodeName)

    Select Case RootName

        Case "HPWH"
            ImportHPWH xmlDoc

        Case "ERWH"
            ImportERWH xmlDoc

        Case "HVAC"
            ImportHVAC xmlDoc

        Case "EV"
            ImportEV xmlDoc

        Case "DRYER"
            ImportDryer xmlDoc

        Case Else
            MsgBox "Unsupported device type: " & RootName, vbCritical
            Exit Sub

    End Select

    'Import common connectivity fields
    ImportConnectivity xmlDoc

    MsgBox "Device imported successfully!", vbInformation

End Sub


Private Sub ImportConnectivity(xmlDoc As Object)

    With Worksheets("Calculator")

        .Range("E31").Value = GetXMLValue(xmlDoc, "//Schedule")
        .Range("E32").Value = GetXMLValue(xmlDoc, "//App")
        .Range("E33").Value = GetXMLValue(xmlDoc, "//Wireless")
        .Range("E34").Value = GetXMLValue(xmlDoc, "//ToU")
        .Range("E35").Value = GetXMLValue(xmlDoc, "//Standard")
        .Range("E36").Value = GetXMLValue(xmlDoc, "//UCM")
        .Range("E37").Value = GetXMLValue(xmlDoc, "//Compliant")
        .Range("E38").Value = GetXMLValue(xmlDoc, "//DataCnfrmnt")
        .Range("E39").Value = GetXMLValue(xmlDoc, "//ShiftCnfrmnt")

    End With

End Sub


Private Sub ImportHPWH(xmlDoc As Object)

    With Worksheets("Calculator")

        .Range("E7").Value = GetXMLValue(xmlDoc, "//CompPwr")
        .Range("E8").Value = GetXMLValue(xmlDoc, "//ResistPwr")
        .Range("E9").Value = GetXMLValue(xmlDoc, "//TankVol")
        .Range("E10").Value = GetXMLValue(xmlDoc, "//MaxWaterTemp")
        .Range("E11").Value = GetXMLValue(xmlDoc, "//MinWaterTemp")
        .Range("E12").Value = GetXMLValue(xmlDoc, "//COPUEF")
        .Range("E13").Value = GetXMLValue(xmlDoc, "//HeatCap")
        .Range("E14").Value = GetXMLValue(xmlDoc, "//ResponseTime")
        .Range("E15").Value = GetXMLValue(xmlDoc, "//CntrlInt")

    End With

End Sub


Private Sub ImportERWH(xmlDoc As Object)

    With Worksheets("Calculator")

        'Example mapping - replace with your ERWH tags
        .Range("E7").Value = GetXMLValue(xmlDoc, "//ElementPower")
        .Range("E8").Value = GetXMLValue(xmlDoc, "//TankVol")
        .Range("E9").Value = GetXMLValue(xmlDoc, "//MaxWaterTemp")
        .Range("E10").Value = GetXMLValue(xmlDoc, "//MinWaterTemp")
        .Range("E11").Value = GetXMLValue(xmlDoc, "//Deadband")
        .Range("E12").Value = GetXMLValue(xmlDoc, "//ResponseTime")
        .Range("E13").Value = GetXMLValue(xmlDoc, "//CntrlInt")

    End With

End Sub


Private Sub ImportHVAC(xmlDoc As Object)

    With Worksheets("Calculator")

        'Example mapping - replace with your HVAC tags
        .Range("E7").Value = GetXMLValue(xmlDoc, "//CoolingCapacity")
        .Range("E8").Value = GetXMLValue(xmlDoc, "//HeatingCapacity")
        .Range("E9").Value = GetXMLValue(xmlDoc, "//COP")
        .Range("E10").Value = GetXMLValue(xmlDoc, "//Setpoint")
        .Range("E11").Value = GetXMLValue(xmlDoc, "//Deadband")
        .Range("E12").Value = GetXMLValue(xmlDoc, "//ResponseTime")
        .Range("E13").Value = GetXMLValue(xmlDoc, "//CntrlInt")

    End With

End Sub


Private Sub ImportEV(xmlDoc As Object)

    With Worksheets("Calculator")

        'To be implemented

    End With

End Sub


Private Sub ImportDryer(xmlDoc As Object)

    With Worksheets("Calculator")

        'To be implemented

    End With

End Sub


Private Function GetXMLValue(xmlDoc As Object, XPath As String) As String

    Dim node As Object

    Set node = xmlDoc.SelectSingleNode(XPath)

    If node Is Nothing Then
        GetXMLValue = ""
    Else
        GetXMLValue = node.Text
    End If

End Function

