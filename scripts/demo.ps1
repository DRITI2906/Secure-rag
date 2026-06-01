# Demo helper — dot-source this before recording:  . .\scripts\demo.ps1
# Then just type:  query "your question here"

$script:base = "https://clustral-app.kindplant-78bc7814.eastus.azurecontainerapps.io"
$script:apiKey = (az containerapp show -n clustral-app -g rg-clustral-rag `
    --query "properties.template.containers[0].env[?name=='API_KEY'].value" -o tsv 2>$null)

function query {
    param([string]$question)

    $resp = Invoke-RestMethod -Uri "$script:base/query" -Method Post `
        -Headers @{"X-API-Key" = $script:apiKey} `
        -ContentType "application/json" `
        -Body (ConvertTo-Json @{question = $question})

    Write-Host ""
    if ($resp.blocked) {
        Write-Host "  BLOCKED" -ForegroundColor Red -NoNewline
        Write-Host "   reason  : $($resp.reason)"
        Write-Host "   answer  : $($resp.answer)"
    } else {
        Write-Host "  ALLOWED" -ForegroundColor Green -NoNewline
        Write-Host "   blocked : false"
        Write-Host "   answer  : $($resp.answer)"
        Write-Host "   citations:"
        $resp.citations | ForEach-Object { Write-Host "     - $_" }
    }
    Write-Host ""
}

Write-Host "Demo ready. Live service: $script:base" -ForegroundColor Cyan
Write-Host "Usage: query `"your question here`"" -ForegroundColor Cyan
Write-Host ""
