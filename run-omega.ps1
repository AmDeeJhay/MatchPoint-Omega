# Windows PowerShell version of run-omega.sh
#   $env:ANTHROPIC_API_KEY = "sk-ant-..."
#   .\run-omega.ps1
# Optional: $env:PROVIDER = "OpenAI" | "ASIOne" | "ASICloud" | "OpenRouter"
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot

$Image    = if ($env:IMAGE) { $env:IMAGE } else { "singularitynet/omega:v0.1.20" }
$Provider = if ($env:PROVIDER) { $env:PROVIDER } else { "Anthropic" }
$Port     = if ($env:PORT) { $env:PORT } else { "8787" }

$map = @{
  "Anthropic"  = @("ANTHROPIC_API_KEY", "Local");
  "OpenAI"     = @("OPENAI_API_KEY", "OpenAI");
  "ASIOne"     = @("ASIONE_API_KEY", "Local");
  "ASICloud"   = @("ASI_API_KEY", "Local");
  "OpenRouter" = @("OPENROUTER_API_KEY", "Local")
}
if (-not $map.ContainsKey($Provider)) { throw "Unknown PROVIDER $Provider" }
$KeyVar = $map[$Provider][0]; $Emb = $map[$Provider][1]
$Key = [Environment]::GetEnvironmentVariable($KeyVar)
if (-not $Key) { throw "Set `$env:$KeyVar first" }

$here = (Get-Location).Path
docker rm -f omega-tennis 2>$null | Out-Null
$dargs = @(
  "run", "-d", "-it", "--name", "omega-tennis", "--init",
  "--security-opt", "no-new-privileges:true",
  "--add-host=host.docker.internal:host-gateway",
  "--tmpfs", "/tmp:size=64m,mode=1777",
  "--tmpfs", "/var/tmp:size=64m,mode=1777",
  "--tmpfs", "/run:size=16m,mode=755",
  "--volume", "omega-tennis-memory:/PeTTa/repos/Omega/memory",
  "--volume", "${here}\omega-plugin\tennis:/PeTTa/repos/Omega/plugins/tennis:ro",
  "--volume", "${here}\omega-plugin\plugins.yaml:/PeTTa/repos/Omega/config/plugins.yaml:ro",
  "-e", "$KeyVar=$Key",
  "-e", "OMEGA_AUTH_SECRET=0000",
  "-e", "IMPORT_KB_ON_START=0",
  $Image,
  "commchannel=websocket", "provider=$Provider", "embeddingprovider=$Emb",
  "securityPolicyPath=/PeTTa/repos/Omega/profile/policy.yaml",
  "WS_URL=ws://host.docker.internal:$Port/agent", "WS_TOKEN="
)
if ($env:MODEL) { $dargs += "model=$($env:MODEL)" }
& docker @dargs
Write-Host "Omega is starting. Watch it with:  docker logs -f omega-tennis"
Write-Host "When the web app header shows 'Omega connected', you're live."
