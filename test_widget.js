const puppeteer = require('puppeteer');
const http = require('http');
const fs = require('fs');
const path = require('path');

// Simple static server
const server = http.createServer((req, res) => {
  let filePath = path.join(__dirname, 'frontend', req.url === '/' ? 'index.html' : req.url.split('?')[0]);
  let extname = path.extname(filePath);
  let contentType = 'text/html';
  switch (extname) {
    case '.js': contentType = 'text/javascript'; break;
    case '.css': contentType = 'text/css'; break;
  }
  fs.readFile(filePath, (err, content) => {
    if (err) {
      if(err.code == 'ENOENT'){
        res.writeHead(404);
        res.end();
      }
      else {
        res.writeHead(500);
        res.end();
      }
    }
    else {
      res.writeHead(200, { 'Content-Type': contentType });
      res.end(content, 'utf-8');
    }
  });
});

server.listen(8123, async () => {
  console.log("Server running at 8123");
  const browser = await puppeteer.launch({headless: true});
  const page = await browser.newPage();
  
  // Test agent dashboard UI
  await page.goto('http://127.0.0.1:8123/agent/admin_dashboard.html', {waitUntil: 'networkidle0'});
  
  await page.evaluate(() => {
    // Click Appearance
    document.getElementById('btn-show-appearance').click();
    
    // Click Widget Tab
    document.querySelector('.theme-tab[data-target="admin-widget-themes"]').click();
    
    // Click Crisp Style
    document.querySelector('.theme-option[data-theme-value="widget-crisp"]').click();
  });
  
  // wait a bit
  await new Promise(r => setTimeout(r, 500));
  
  const widgetTheme = await page.evaluate(() => localStorage.getItem('wrennon_widget_theme'));
  console.log("Widget Theme in localStorage after clicking Crisp Style:", widgetTheme);
  
  const isActive = await page.evaluate(() => document.querySelector('.theme-option[data-theme-value="widget-crisp"]').classList.contains('active'));
  console.log("Is Crisp option active?:", isActive);
  
  await page.reload({waitUntil: 'networkidle0'});
  
  // Check if theme applied
  const classList = await page.evaluate(() => {
    return document.getElementById('wrennon-widget').className;
  });
  
  const defaultHeadDisplay = await page.evaluate(() => {
    return window.getComputedStyle(document.getElementById('panel-header')).display;
  });
  
  const crispHeadDisplay = await page.evaluate(() => {
    return window.getComputedStyle(document.getElementById('panel-header-crisp')).display;
  });
  
  console.log("wrennon-widget classes:", classList);
  console.log("default header display:", defaultHeadDisplay);
  console.log("crisp header display:", crispHeadDisplay);
  
  await browser.close();
  server.close();
  process.exit(0);
});
