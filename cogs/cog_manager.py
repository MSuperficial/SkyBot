from typing import Annotated

from discord.ext import commands

from .emoji_manager import Emojis
from .helper.formats import code_block

__all__ = ("CogManager",)

_cogs_dict = {}


class ExtName:
    @classmethod
    async def convert(cls, ctx, ext_name: str):
        return "cogs." + ext_name

    @classmethod
    def get_root(cls, ext_name: str):
        return ext_name.split(".")[-1]


class CogManager(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def cog_check(self, ctx: commands.Context):  # type: ignore
        # 限制只有owner可以调用这些命令
        return await commands.is_owner().predicate(ctx)

    async def cog_command_error(self, ctx: commands.Context, error):
        if isinstance(error, commands.NotOwner):
            await ctx.send("`You do not have permission!`")

    def _create_cog(self, name):
        cog = _cogs_dict.get(name)
        if cog is not None:
            cog = cog(self.bot)
        return cog

    @commands.command()
    async def enable(self, ctx: commands.Context, cog_name):
        cog = self._create_cog(cog_name)
        if cog is None:
            await ctx.send(f"`No function named {cog_name}.`")
        else:
            await self.bot.add_cog(cog, override=True)
            await ctx.message.add_reaction(Emojis("success", "✅"))

    @commands.command()
    async def disable(self, ctx: commands.Context, cog_name):
        # 禁止禁用自己的功能
        if cog_name == CogManager.__name__ or self.bot.get_cog(cog_name) is None:
            await ctx.send(f"`No function named {cog_name}.`")
        else:
            await self.bot.remove_cog(cog_name)
            await ctx.message.add_reaction(Emojis("success", "✅"))

    @commands.command()
    async def load(self, ctx: commands.Context, ext_name: Annotated[str, ExtName]):
        await self.bot.load_extension(ext_name)
        await ctx.message.add_reaction(Emojis("success", "✅"))

    @commands.command()
    async def unload(self, ctx: commands.Context, ext_name: Annotated[str, ExtName]):
        await self.bot.unload_extension(ext_name)
        await ctx.message.add_reaction(Emojis("success", "✅"))

    @commands.command()
    async def reload(self, ctx: commands.Context, ext_name: Annotated[str, ExtName]):
        await self.bot.reload_extension(ext_name)
        await ctx.message.add_reaction(Emojis("success", "✅"))

    @load.error
    @unload.error
    @reload.error
    async def load_error(self, ctx: commands.Context, error):
        error = error.original
        if not isinstance(error, commands.ExtensionError):
            return
        ext_name = ExtName.get_root(error.name)
        if isinstance(error, commands.ExtensionNotFound):
            # 找不到扩展文件或无法导入
            await ctx.send(f"`No extension named {ext_name} found.`")
        elif isinstance(error, commands.ExtensionAlreadyLoaded):
            # 重复加载忽略
            pass
        elif isinstance(error, commands.NoEntryPointError):
            # 缺少setup方法
            await ctx.send(f"`{ext_name} is not an extension.`")
        elif isinstance(error, commands.ExtensionFailed):
            # 其他异常
            err_msg = str(error.original)
            msg = f"Extension loading failed: {err_msg}"
            msg = code_block(msg) if err_msg.find("\n") != -1 else "`" + msg + "`"
            await ctx.send(msg)
        elif (
            isinstance(error, commands.ExtensionNotLoaded)
            and ctx.command.name == self.reload.name  # type: ignore
        ):
            # 卸载未加载的功能
            await ctx.send(f"`No extension named {ext_name} was loaded.`")

    @commands.command()
    async def sync(self, ctx: commands.Context):
        try:
            synced = await self.bot.tree.sync()
            await ctx.send(
                f"Synced {len(synced)} commands globally:\n{', '.join([c.name for c in synced])}"
            )
        except Exception as e:
            msg = f"Error while syncing: {str(e)}"
            msg = code_block(msg) if msg.find("\n") != -1 else "`" + msg + "`"
            await ctx.send(msg)
