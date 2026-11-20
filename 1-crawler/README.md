

-第一步，
```angular2html
"C:\Program Files\Google\Chrome\Application\chrome.exe" ^
  --remote-debugging-port=9222 ^
  --user-data-dir="%USERPROFILE%\.chrome-cdp-profile" ^
  --no-first-run --no-default-browser-check ^
  https://people.com/
```

第二步，

验证 http://127.0.0.1:9222/json/version 有 JSON 返回

第三步，
IntelliJ → Run Configuration → Program arguments 只填：

--cdp=http://127.0.0.1:9222