$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$property = [System.Windows.Automation.AutomationElement]::IsTextPatternAvailableProperty
$condition = [System.Windows.Automation.PropertyCondition]::new($property, $true)
while ($handle = [Console]::ReadLine()) {
    try {
        $root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]([Int64]$handle))
        $element = $root.FindFirst([System.Windows.Automation.TreeScope]::Descendants, $condition)
        $pattern = $element.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
        $text = ($pattern.GetVisibleRanges() | ForEach-Object { $_.GetText(-1) }) -join ([char]10)
        [Console]::WriteLine((ConvertTo-Json -Compress -InputObject $text))
    } catch {
        [Console]::WriteLine((ConvertTo-Json -Compress -InputObject ("UIA: "+$_.Exception.Message)))
    }
}
