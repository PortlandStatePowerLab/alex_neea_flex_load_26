Option Explicit
Private Const SUPPORTED_VERSION As String = "1.0"

Sub ImportDevice()

    Dim xmlDoc As Object
    
    Dim fd As FileDialog
    
    Set fd = Application.FileDialog(msoFileDialogFilePicker)
      
    Dim SelectedFile As String
    
    With fd
    
    .Title = "Select an xml file for the flex load you would like to study"
    .Filters.Clear
    .Filters.Add "XML Files", "*.xml"
    .AllowMultiSelect = False
    
    If .Show = -1 Then
    
        SelectedFile = .SelectedItems(1)
        
        Set xmlDoc = CreateObject("MSXML2.DOMDocument.6.0")
        
        xmlDoc.async = False
        xmlDoc.validateOnParse = False
        
        Dim FileLoaded As Boolean
        
        FileLoaded = xmlDoc.Load(SelectedFile)
        
        If FileLoaded = True Then
            
            Dim XMLVersion As String
            XMLVersion = GetXMLValue(xmlDoc, "FlexLoad/Version")
            
            If XMLVersion <> SUPPORTED_VERSION Then
                MsgBox "This XML file is version " & XMLVersion & _
                ", but this calculator supports version " & _
                SUPPORTED_VERSION & ".", vbCritical
                
                Exit Sub
                
            Else
                LoadXMLValue xmlDoc, "FLName", "FlexLoad/Name"
                
                LoadXMLValue xmlDoc, "UpRegCap", "FlexLoad/Capacity/UpRegCap"
                LoadXMLValue xmlDoc, "DwnRegCap", "FlexLoad/Capacity/DwnRegCap"
                LoadXMLValue xmlDoc, "UpEnergyDur", "FlexLoad/Capacity/UpEnergyDur"
                LoadXMLValue xmlDoc, "DwnEnergyDur", "FlexLoad/Capacity/DwnEnergyDur"
                
                LoadXMLValue xmlDoc, "ResponseTime", "FlexLoad/Performance/ResponseTime"
                LoadXMLValue xmlDoc, "Latency", "FlexLoad/Performance/Latency"
                LoadXMLValue xmlDoc, "CntrlInt", "FlexLoad/Performance/CntrlInt"
                
                LoadXMLValue xmlDoc, "Sched", "FlexLoad/Control/Sched"
                LoadXMLValue xmlDoc, "App", "FlexLoad/Control/App"
                LoadXMLValue xmlDoc, "Wireless", "FlexLoad/Control/Wireless"
                LoadXMLValue xmlDoc, "ToU", "FlexLoad/Control/ToU"
                
                LoadXMLValue xmlDoc, "Standards", "FlexLoad/Interop/Standards"
                LoadXMLValue xmlDoc, "UCM", "FlexLoad/Interop/UCM"
                LoadXMLValue xmlDoc, "Compliant", "FlexLoad/Interop/Compliant"
                LoadXMLValue xmlDoc, "DataCnfrmnt", "FlexLoad/Interop/DataCnfrmnt"
                LoadXMLValue xmlDoc, "ShiftCnfrmnt", "FlexLoad/Interop/ShiftCnfrmnt"
                
            
            End If
                
        
        Else
            MsgBox "The file didn't load :("
        
        End If
    
    Else
        Exit Sub
    
    End If
    
    End With
    
    Set fd = Nothing

End Sub

Private Function GetXMLValue(xmlDoc As Object, NodePath As String) As String

    Dim Node As Object

    Set Node = xmlDoc.SelectSingleNode(NodePath)

    If Node Is Nothing Then
        GetXMLValue = ""
    Else
        GetXMLValue = Node.Text
    End If

End Function

Private Sub LoadXMLValue(xmlDoc As Object, _
                         CellName As String, _
                         NodePath As String)

    Range(CellName).Value = GetXMLValue(xmlDoc, NodePath)

End Sub
