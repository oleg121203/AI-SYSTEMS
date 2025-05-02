To test the provided JavaScript file, we can use Jest, a popular testing framework for JavaScript. Since the provided code is for a Phaser game, we'll focus on testing the functions and logic rather than the Phaser-specific functionality. We'll also mock the Phaser game instance and its methods to isolate the tests.

Here's a complete set of tests using Jest:

```javascript
// Import the functions to be tested
const {
  preload,
  create,
  update,
  collectCoin,
  hitEnemy,
  createEnemies
} = require('./path/to/your/file'); // Adjust the path as necessary

// Mock Phaser Game instance and methods
const mockPhaser = {
  load: {
    image: jest.fn(),
    spritesheet: jest.fn()
  },
  physics: {
    add: {
      staticGroup: jest.fn().mockReturnValue({
        create: jest.fn()
      }),
      sprite: jest.fn().mockReturnValue({
        setBounce: jest.fn(),
        setCollideWorldBounds: jest.fn()
      }),
      group: jest.fn().mockReturnValue({
        children: {
          iterate: jest.fn()
        },
        countActive: jest.fn()
      })
    }
  },
  add: {
    image: jest.fn(),
    text: jest.fn().mockReturnValue({
      setText: jest.fn()
    })
  },
  anims: {
    create: jest.fn(),
    generateFrameNumbers: jest.fn(),
    play: jest.fn()
  },
  input: {
    keyboard: {
      createCursorKeys: jest.fn().mockReturnValue({
        left: { isDown: false },
        right: { isDown: false },
        up: { isDown: false }
      })
    }
  },
  Math: {
    FloatBetween: jest.fn().mockReturnValue(0.5),
    Between: jest.fn().mockReturnValue(100)
  }
};

// Mock global variables
let player;
let cursors;
let coins;
let score = 0;
let scoreText;
let lives = 3;
let livesText;
let level = 1;
let enemies;

describe('Phaser Game Functions', () => {
  beforeEach(() => {
    // Reset mocks and global variables before each test
    jest.clearAllMocks();
    player = mockPhaser.physics.add.sprite();
    cursors = mockPhaser.input.keyboard.createCursorKeys();
    coins = mockPhaser.physics.add.group();
    score = 0;
    scoreText = mockPhaser.add.text();
    lives = 3;
    livesText = mockPhaser.add.text();
    level = 1;
    enemies = mockPhaser.physics.add.group();
  });

  test('preload function loads assets', () => {
    preload.call(mockPhaser);
    expect(mockPhaser.load.image).toHaveBeenCalledWith('sky', 'assets/sky.png');
    expect(mockPhaser.load.image).toHaveBeenCalledWith('ground', 'assets/platform.png');
    expect(mockPhaser.load.image).toHaveBeenCalledWith('coin', 'assets/coin.png');
    expect(mockPhaser.load.spritesheet).toHaveBeenCalledWith('dude', 'assets/dude.png', { frameWidth: 32, frameHeight: 48 });
    expect(mockPhaser.load.spritesheet).toHaveBeenCalledWith('enemy', 'assets/enemy.png', { frameWidth: 32, frameHeight: 32 });
  });

  test('create function initializes game objects', () => {
    create.call(mockPhaser);
    expect(mockPhaser.add.image).toHaveBeenCalledWith(128, 120, 'sky');
    expect(mockPhaser.physics.add.staticGroup().create).toHaveBeenCalled();
    expect(mockPhaser.physics.add.sprite).toHaveBeenCalledWith(100, 450, 'dude');
    expect(mockPhaser.anims.create).toHaveBeenCalledTimes(3);
    expect(mockPhaser.input.keyboard.createCursorKeys).toHaveBeenCalled();
    expect(mockPhaser.physics.add.group).toHaveBeenCalledTimes(2);
    expect(mockPhaser.add.text).toHaveBeenCalledWith(16, 16, 'Score: 0', { fontSize: '32px', fill: '#000' });
    expect(mockPhaser.add.text).toHaveBeenCalledWith(16, 50, 'Lives: 3', { fontSize: '32px', fill: '#000' });
  });

  test('update function handles player movement', () => {
    cursors.left.isDown = true;
    update.call(mockPhaser);
    expect(player.setVelocityX).toHaveBeenCalledWith(-160);
    expect(player.anims.play).toHaveBeenCalledWith('left', true);

    cursors.left.isDown = false;
    cursors.right.isDown = true;
    update.call(mockPhaser);
    expect(player.setVelocityX).toHaveBeenCalledWith(160);
    expect(player.anims.play).toHaveBeenCalledWith('right', true);

    cursors.right.isDown = false;
    update.call(mockPhaser);
    expect(player.setVelocityX).toHaveBeenCalledWith(0);
    expect(player.anims.play).toHaveBeenCalledWith('turn');
  });

  test('collectCoin function updates score and respawns coins', () => {
    const coin = { disableBody: jest.fn() };
    collectCoin(player, coin);
    expect(coin.disableBody).toHaveBeenCalledWith(true, true);
    expect(score).toBe(10);
    expect(scoreText.setText).toHaveBeenCalledWith('Score: 10');

    coins.countActive.mockReturnValue(0);
    collectCoin(player, coin);
    expect(coins.children.iterate).toHaveBeenCalled();
    expect(enemies.create).toHaveBeenCalled();
  });

  test('hitEnemy function reduces lives and handles game over', () => {
    const enemy = {};
    hitEnemy.call(mockPhaser, player, enemy);
    expect(lives).toBe(2);
    expect(livesText.setText).toHaveBeenCalledWith('Lives: 2');

    lives = 0;
    hitEnemy.call(mockPhaser, player, enemy);
    expect(mockPhaser.physics.pause).toHaveBeenCalled();
    expect(player.setTint).toHaveBeenCalledWith(0xff0000);
    expect(player.anims.play).toHaveBeenCalledWith('turn');
  });

  test('createEnemies function creates enemies', () => {
    createEnemies.call(mockPhaser);
    expect(enemies.create).toHaveBeenCalled();
  });
});
```

### Explanation:
1. **Mocking Phaser**: We mock the Phaser game instance and its methods to isolate the tests. This allows us to focus on testing the logic of the functions without relying on the actual Phaser library.
2. **Global Variables**: We define global variables used in the game and reset them before each test.
3. **Tests**:
   - **preload**: Tests that the `preload` function loads the correct assets.
   - **create**: Tests that the `create` function initializes game objects correctly.
   - **update**: Tests that the `update` function handles player movement based on cursor input.
   - **collectCoin**: Tests that the `collectCoin` function updates the score and respawns coins.
   - **hitEnemy**: Tests that the `hitEnemy` function reduces lives and handles game over.
   - **createEnemies**: Tests that the `createEnemies` function creates enemies.

### Running the Tests:
To run the tests, ensure you have Jest installed and configured in your project. You can run the tests using the following command:
```bash
npx jest
```

This setup provides a comprehensive test suite for the provided JavaScript file, covering function logic, player movement, and game state management.