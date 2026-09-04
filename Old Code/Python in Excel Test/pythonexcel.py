# Solve the quadratic equation ax**2 + bx + c = 0

# import complex math module
import cmath
import win32com.client

excel = win32com.client.GetActiveObject("Excel.Application")
wb = excel.ActiveWorkbook

inputs = wb.Worksheets("Calculator")

a = inputs.Range("B2").Value
b = inputs.Range("B3").Value
c = inputs.Range("B4").Value

# calculate the discriminant
d = (b**2) - (4*a*c)

# find two solutions
sol1 = (-b-cmath.sqrt(d))/(2*a)
sol2 = (-b+cmath.sqrt(d))/(2*a)

results = wb.Worksheets("Calculator")
results.Range("D2").Value = sol1.real
results.Range("D3").Value = sol2.real

excel.Calculate()