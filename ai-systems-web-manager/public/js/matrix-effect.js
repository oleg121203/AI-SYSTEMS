// Matrix rain effect
document.addEventListener('DOMContentLoaded', function() {
  const canvas = document.createElement('canvas');
  const matrixRain = document.getElementById('matrix-rain');
  matrixRain.appendChild(canvas);
  
  const ctx = canvas.getContext('2d');
  
  // Make canvas full screen
  canvas.width = window.innerWidth;
  canvas.height = window.innerHeight;
  
  // Characters to use
  const chars = '01アイウエオカキクケコサシスセソタチツテトナニヌネノハヒフヘホマミムメモヤユヨラリルレロワヲン';
  const charArray = chars.split('');
  
  // Font size and columns
  const fontSize = 14;
  const columns = Math.floor(canvas.width / fontSize);
  
  // Array to track the y position of each column
  const drops = [];
  
  // Initialize drops at random positions
  for (let i = 0; i < columns; i++) {
    drops[i] = Math.floor(Math.random() * -canvas.height);
  }
  
  // Drawing function
  function draw() {
    // Set semi-transparent black background
    ctx.fillStyle = 'rgba(0, 0, 0, 0.05)';
    ctx.fillRect(0, 0, canvas.width, canvas.height);
    
    // Set text color and font
    ctx.fillStyle = '#00ff00';
    ctx.font = `${fontSize}px monospace`;
    
    // Draw characters
    for (let i = 0; i < drops.length; i++) {
      // Random character
      const char = charArray[Math.floor(Math.random() * charArray.length)];
      
      // Draw the character
      const x = i * fontSize;
      const y = drops[i] * fontSize;
      
      // Vary the opacity based on position
      const opacity = Math.random() * 0.5 + 0.3;
      ctx.fillStyle = `rgba(0, 255, 0, ${opacity})`;
      
      ctx.fillText(char, x, y);
      
      // Move the drop down
      drops[i]++;
      
      // Reset drop when it reaches bottom or randomly
      if (drops[i] * fontSize > canvas.height && Math.random() > 0.975) {
        drops[i] = Math.floor(Math.random() * -20);
      }
    }
  }
  
  // Resize handler
  window.addEventListener('resize', function() {
    canvas.width = window.innerWidth;
    canvas.height = window.innerHeight;
    
    // Recalculate columns
    const newColumns = Math.floor(canvas.width / fontSize);
    
    // Adjust drops array
    if (newColumns > columns) {
      // Add new columns
      for (let i = columns; i < newColumns; i++) {
        drops[i] = Math.floor(Math.random() * -canvas.height);
      }
    } else {
      // Remove excess columns
      drops.length = newColumns;
    }
  });
  
  // Run the animation
  setInterval(draw, 50);
  
  // Terminal time
  const terminalTime = document.getElementById('terminal-time');
  
  function updateTerminalTime() {
    const now = new Date();
    const hours = String(now.getHours()).padStart(2, '0');
    const minutes = String(now.getMinutes()).padStart(2, '0');
    const seconds = String(now.getSeconds()).padStart(2, '0');
    terminalTime.textContent = `${hours}:${minutes}:${seconds}`;
  }
  
  // Update time every second
  setInterval(updateTerminalTime, 1000);
  updateTerminalTime(); // Initial update
});
