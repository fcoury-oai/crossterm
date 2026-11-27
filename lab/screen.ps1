$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.UTF8Encoding]::new($false)
Add-Type -AssemblyName UIAutomationClient
Add-Type -AssemblyName UIAutomationTypes
$property = [System.Windows.Automation.AutomationElement]::IsTextPatternAvailableProperty
$condition = [System.Windows.Automation.PropertyCondition]::new($property, $true)
while ($handle = [Console]::ReadLine()) {
    try {
        $root = [System.Windows.Automation.AutomationElement]::FromHandle([IntPtr]([Int64]$handle))
        $elements = $root.FindAll([System.Windows.Automation.TreeScope]::Descendants, $condition)
        $text = ""
        foreach ($element in $elements) {
            $pattern = $element.GetCurrentPattern([System.Windows.Automation.TextPattern]::Pattern)
            $candidate = ($pattern.GetVisibleRanges() | ForEach-Object { $_.GetText(-1) }) -join ([char]10)
            if ($candidate.Length -gt $text.Length) { $text = $candidate }
        }
        [Console]::WriteLine((ConvertTo-Json -Compress -InputObject $text))
    } catch {
        [Console]::WriteLine((ConvertTo-Json -Compress -InputObject ("UIA: "+$_.Exception.Message)))
    }
}
