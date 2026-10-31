# Run this script as Administrator to allow Phone B to reach port 8000
# Usage: Right-click PowerShell > "Run as Administrator" > paste this

Write-Host "Adding Windows Firewall inbound rule for RESQ Backend (port 8000)..."

New-NetFirewallRule `
  -DisplayName "RESQ Backend TCP 8000" `
  -Direction Inbound `
  -LocalPort 8000 `
  -Protocol TCP `
  -Action Allow `
  -Profile Private,Domain `
  -Description "Allows Phone B SMS forwarder to reach the RESQ FastAPI backend on the local hotspot network."

Write-Host ""
Write-Host "Done! Verify with:"
Write-Host "  Get-NetFirewallRule -DisplayName 'RESQ Backend TCP 8000'"
Write-Host ""
Write-Host "Your current LAN IPv4 addresses:"
Get-NetIPAddress -AddressFamily IPv4 | Where-Object { $_.InterfaceAlias -notlike "*Loopback*" } |
  Select-Object InterfaceAlias, IPAddress | Format-Table -AutoSize

