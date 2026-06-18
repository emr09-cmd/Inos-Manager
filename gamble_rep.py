import random
import discord
from discord import app_commands
from discord.ext import commands
from discord.ui import Button, View

# ==========================================
# 1. CORE GAME LOGIC ENGINE
# ==========================================
class DiamondGame:
    def __init__(self, rows=5, cols=5, num_bombs=1):
        self.rows = rows
        self.cols = cols
        self.num_bombs = num_bombs
        # Generates row-column markers like [['A1', 'B1'...], ['A2', 'B2'...]]
        self.grid_labels = [
            [f"{chr(65 + r)}{c + 1}" for c in range(cols)] for r in range(rows)
        ]
        self.bombs = set()
        self.revealed = set()
        self.game_over = False
        self.won = False
        
        self._generate_board()

    def _generate_board(self):
        all_coords = [(r, c) for r in range(self.rows) for c in range(self.cols)]
        bomb_coords = random.sample(all_coords, self.num_bombs)
        self.bombs = set(bomb_coords)

    def choose_square(self, row: int, col: int) -> str:
        if (row, col) in self.revealed or self.game_over:
            return "already_revealed"

        if (row, col) in self.bombs:
            self.game_over = True
            return "bomb"

        self.revealed.add((row, col))
        
        total_squares = self.rows * self.cols
        if len(self.revealed) == (total_squares - self.num_bombs):
            self.game_over = True
            self.won = True
            
        return "diamond"


# ==========================================
# 2. DISCORD INTERACTION UI COMPONENTS
# ==========================================
class GambleButton(Button):
    def __init__(self, row_idx, col_idx, label):
        super().__init__(
            label=label, 
            style=discord.ButtonStyle.secondary, 
            row=row_idx
        )
        self.row_idx = row_idx
        self.col_idx = col_idx

    async def callback(self, interaction: discord.Interaction):
        view: GambleView = self.view
        
        # Enforce that only the author can interact with their matrix
        if interaction.user.id != view.user_id:
            await interaction.response.send_message(
                "This isn't your game! Start your own with `/gamble`.", 
                ephemeral=True
            )
            return

        result = view.game.choose_square(self.row_idx, self.col_idx)

        if result == "bomb":
            self.style = discord.ButtonStyle.danger
            self.emoji = "💣"
            self.label = None
            view.disable_all_buttons()
            await interaction.response.edit_message(
                content=f"💥 **BOOM!** You hit the bomb and lost! Better luck next time, {interaction.user.mention}.", 
                view=view
            )
            view.stop()

        elif result == "diamond":
            self.style = discord.ButtonStyle.success
            self.emoji = "💎"
            
            if view.game.won:
                view.disable_all_buttons()
                await interaction.response.edit_message(
                    content=f"🏆 **Congratulations {interaction.user.mention}!** You found all the diamonds safely!", 
                    view=view
                )
                view.stop()
            else:
                await interaction.response.edit_message(view=view)


class GambleView(View):
    def __init__(self, user_id: int):
        super().__init__(timeout=180.0) # Times out after 3 minutes
        self.user_id = user_id
        self.game = DiamondGame()
        self._build_grid()

    def _build_grid(self):
        for r in range(self.game.rows):
            for c in range(self.game.cols):
                label = self.game.grid_labels[r][c]
                self.add_item(GambleButton(row_idx=r, col_idx=c, label=label))

    def disable_all_buttons(self):
        for item in self.children:
            if isinstance(item, Button):
                item.disabled = True


# ==========================================
# 3. DISCORD EXTENSION / COG CONTAINER
# ==========================================
class GambleRepController(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    @app_commands.command(name="gamble", description="Avoid the bomb and reveal all diamonds!")
    async def gamble(self, interaction: discord.Interaction):
        view = GambleView(user_id=interaction.user.id)
        
        welcome_text = (
            "### Avoid the bomb and reveal all diamonds!\n"
            "Click any square below to play.\n\n"
            "Good luck! 🎲"
        )
        
        await interaction.response.send_message(content=welcome_text, view=view)


# Mandated entrypoint hook for 'bot.load_extension()' execution lines
async def setup(bot: commands.Bot):
    await bot.add_cog(GambleRepController(bot))