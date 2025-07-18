import os
from pathlib import Path
from typing import TypedDict

import discord
from discord import ButtonStyle, Interaction, app_commands, ui
from discord.ext import commands, tasks

from sky_m8 import SkyM8
from utils.remote_config import remote_config

from ..base.views import AutoDisableView, LongTextModal, ShortTextModal
from ..helper.embeds import fail, success
from ..helper.var_parser import VarParser

__all__ = ("Welcome",)


class _MsgCfg(TypedDict):
    ping: bool
    showAvatar: bool
    color: str
    title: str
    content: str
    footer: str
    image: str


class Welcome(commands.Cog):
    _WELCOME_KEY = "welcomeSetup"
    _DEFAULT_MSG = _MsgCfg(
        ping=False,
        showAvatar=True,
        color="#5865F2",
        title="Welcome to {server.name}",
        content="We are glad to have you here, {member.mention}.",
        footer="You are the {member.ordinal} member of this server",
        image="{randomImage}",
    )
    group_welcome = app_commands.Group(
        name="welcome",
        description="Commands to setup welcome for new members.",
        allowed_contexts=app_commands.AppCommandContext(dm_channel=False),
        allowed_installs=app_commands.AppInstallationType(user=False),
        default_permissions=discord.Permissions(manage_guild=True),
    )

    def __init__(self, bot: SkyM8):
        self.bot = bot
        self._img_types = ["jpg", "jpeg", "png", "webp", "gif"]

    async def cog_load(self):
        self._find_db_channel.start()

    @tasks.loop(count=1)
    async def _find_db_channel(self):
        await self.bot.wait_until_ready()
        db_id = int(os.getenv("DATABASE_CHANNEL", "0"))
        self._db_channel: discord.TextChannel | None = self.bot.get_channel(db_id)  # type: ignore

    def _is_img_file_valid(self, file: discord.Attachment):
        mime = file.content_type
        suffix = Path(file.filename).suffix[1:]
        return mime and mime[6:] in self._img_types and suffix in self._img_types

    async def fetch_welcome_msg(self, guild_id: int):
        msg: _MsgCfg = await remote_config.get_json(self._WELCOME_KEY, guild_id, "message")  # type: ignore # fmt: skip
        msg = msg or await remote_config.get_json(self._WELCOME_KEY, 0, "message")
        msg = msg or self._DEFAULT_MSG
        return msg

    async def fetch_valid_welcome_roles(self, guild: discord.Guild):
        role_ids: list[str] = (
            await remote_config.get_json(self._WELCOME_KEY, guild.id, "roles") or []
        )  # type: ignore
        roles = [r for id in role_ids if (r := guild.get_role(int(id)))]
        roles = [r for r in roles if r.is_assignable()]
        return roles

    @commands.Cog.listener()
    async def on_member_join(self, member: discord.Member):
        # welcome功能忽略bot用户
        if member.bot:
            return
        guild = member.guild
        # 检查权限并设置角色
        if guild.me.guild_permissions.manage_roles:
            roles = await self.fetch_valid_welcome_roles(guild)
            if roles:
                await member.add_roles(*roles, reason="Default roles")
        # 检查系统频道并发送欢迎消息
        if guild.system_channel:
            msg_cfg = await self.fetch_welcome_msg(guild.id)
            builder = WelcomeMessageBuilder(
                VarParser.from_member_join(self.bot, member)
            )
            msg_data = builder.build(msg_cfg)
            await guild.system_channel.send(**msg_data)

    @group_welcome.command(name="enable", description="Switch welcome features, by default all False.")  # fmt: skip
    @app_commands.describe(
        message="Whether to send welcome message, leave empty to keep it as is.",
    )
    async def welcome_enable(
        self,
        interaction: Interaction,
        message: bool | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild: discord.Guild = interaction.guild  # type: ignore
        options = {
            "message": message,
        }
        # 筛选选项并设置
        options = {k: v for k, v in options.items() if v is not None}
        await remote_config.merge_json(
            self._WELCOME_KEY, guild.id, "enable", value=options
        )
        # 获取当前选项并展示
        options = await remote_config.get_json(self._WELCOME_KEY, guild.id, "enable")
        await interaction.followup.send(
            embed=discord.Embed(
                color=discord.Color.greyple(),
                title="Welcome feature options",
                description="\n".join(
                    [f"`{k}` : {'Yes' if v else 'No'}" for k, v in options.items()]  # type: ignore
                ),
            ),
        )

    @group_welcome.command(name="message", description="Edit welcome message.")
    async def welcome_message(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        # 获取消息配置
        msg_cfg = await self.fetch_welcome_msg(interaction.guild.id)  # type: ignore
        # 生成消息
        builder = WelcomeMessageBuilder(VarParser.from_interaction(interaction))
        msg_data = builder.build(msg_cfg)
        view = WelcomeMessageView(msg_cfg=msg_cfg, builder=builder)
        msg = await interaction.followup.send(**msg_data, view=view)
        view.response_msg = msg

    @group_welcome.command(
        name="image",
        description="Set image in welcome message, either upload a file or use an url.",
    )
    @app_commands.describe(
        file="Upload an image file.",
        url="Use an image url.",
    )
    async def welcome_image(
        self,
        interaction: Interaction,
        file: discord.Attachment | None = None,
        url: str | None = None,
    ):
        await interaction.response.defer(ephemeral=True)
        guild: discord.Guild = interaction.guild  # type: ignore
        if not await remote_config.exists_json(self._WELCOME_KEY, guild.id, "message"):
            # 需要先设置消息才能单独更改图片
            await interaction.followup.send(embed=fail("Please set message first"))
            return
        if not file and not url:
            # 至少要指定一个参数
            await interaction.followup.send(embed=fail("Both options are empty"))
            return
        if file:
            # 需要设置database频道以支持文件上传
            if not self._db_channel:
                await interaction.followup.send(
                    embed=fail("File uploading not available")
                )
                return
            # 检查图片文件格式
            if not self._is_img_file_valid(file):
                valid_types = ", ".join([f"`{t}`" for t in self._img_types])
                await interaction.followup.send(
                    embed=fail("Format not supported", "Only support " + valid_types),
                )
                return
            # 发送文件至database频道并获取url
            f = await file.to_file()
            msg = await self._db_channel.send(
                content=f"Welcome image for **{guild.name}** `{guild.id}`",
                file=f,
            )
            url = msg.attachments[0].url
        try:
            await interaction.followup.send(
                embed=discord.Embed(
                    color=discord.Color.green(),
                    title="Welcome image saved",
                ).set_image(url=url)
            )
            # 保存图像url
            await remote_config.set_json(
                self._WELCOME_KEY, guild.id, "message", "image", value=url
            )
        except discord.HTTPException as ex:
            if ex.status == 400:
                # url格式错误
                await interaction.followup.send(embed=fail("Invalid url format"))
            else:
                await interaction.followup.send(embed=fail("Error while saving", ex))

    @group_welcome.command(name="roles", description="Set default roles for new members.")  # fmt: skip
    async def welcome_roles(self, interaction: Interaction):
        await interaction.response.defer(ephemeral=True)
        guild: discord.Guild = interaction.guild  # type: ignore
        # 检查权限
        if not guild.me.guild_permissions.manage_roles:
            await interaction.followup.send(
                embed=fail(
                    "Missing permission",
                    f"Please add `Manage Roles` permission for {guild.me.mention} first.",
                ),
            )
            return
        # 获取有效角色
        roles = await self.fetch_valid_welcome_roles(guild)
        view = WelcomeRolesView(default_roles=roles)
        msg = await interaction.followup.send(
            content="### Select default roles for new member:",
            view=view,
        )
        view.response_msg = msg

    @group_welcome.command(name="preview", description="Preview welcome message for selected member.")  # fmt: skip
    @app_commands.describe(
        member="The member to welcome, by default is yourself.",
        private="Only you can see the message, by default True.",
    )
    async def welcome_preview(
        self,
        interaction: Interaction,
        member: discord.Member | None = None,
        private: bool = True,
    ):
        await interaction.response.defer(ephemeral=private)
        # 获取消息配置
        msg_cfg = await self.fetch_welcome_msg(interaction.guild.id)  # type: ignore
        # 生成消息
        builder = WelcomeMessageBuilder(
            VarParser.from_interaction(interaction, user=member)
        )
        msg_data = builder.build(msg_cfg)
        await interaction.followup.send(**msg_data)


class WelcomeMessageBuilder:
    def __init__(self, parser: VarParser):
        self.parser = parser
        self.member: discord.Member = parser.context.member  # type: ignore

    def build(self, config: _MsgCfg):
        cfg_copy = config.copy()
        for k, v in cfg_copy.items():
            if isinstance(v, str):
                v = self.parser.parse(v)
                cfg_copy[k] = v
        if not cfg_copy["color"]:
            color = None
        else:
            color = discord.Color.from_str(cfg_copy["color"])
        embed = (
            discord.Embed(
                color=color,
                title=cfg_copy["title"],
                description=cfg_copy["content"],
            )
            .set_footer(text=cfg_copy["footer"])
            .set_image(url=cfg_copy["image"])
        )
        if cfg_copy["showAvatar"]:
            embed.set_author(
                name=self.member.display_name,
                icon_url=self.member.display_avatar.url,
            )
        content = self.member.mention if cfg_copy["ping"] else None
        return {
            "content": content,
            "embed": embed,
        }


class WelcomeMessageView(AutoDisableView):
    def __init__(self, *, msg_cfg: _MsgCfg, builder: WelcomeMessageBuilder):
        # 设置为840秒，因为900秒后消息会到期超时
        super().__init__(timeout=840)
        self.add_item(
            ui.Button(
                style=ButtonStyle.url,
                label="Color Picker",
                emoji="🎨",
                url="https://g.co/kgs/Pxm4qRy",
                row=2,
            )
        )
        self.msg_cfg = msg_cfg
        self.builder = builder

    async def update_message(self, interaction: Interaction):
        msg_data = self.builder.build(self.msg_cfg)
        await interaction.edit_original_response(**msg_data)

    @ui.button(label="Toggle ping", row=0)
    async def toggle_ping(self, interaction: Interaction, button):
        await interaction.response.defer()
        self.msg_cfg["ping"] = not self.msg_cfg["ping"]
        await self.update_message(interaction)

    @ui.button(label="Toggle avatar", row=0)
    async def toggle_avatar(self, interaction: Interaction, button):
        await interaction.response.defer()
        self.msg_cfg["showAvatar"] = not self.msg_cfg["showAvatar"]
        await self.update_message(interaction)

    @ui.button(label="Title", row=1)
    async def edit_title(self, interaction: Interaction, button):
        modal = ShortTextModal(
            title="Set message title",
            label="Title (Optional)",
            default=self.msg_cfg["title"],
            required=False,
        )
        await interaction.response.send_modal(modal)
        await modal.wait()
        self.msg_cfg["title"] = modal.text.value
        await self.update_message(interaction)

    @ui.button(label="Content", row=1)
    async def edit_content(self, interaction: Interaction, button):
        modal = LongTextModal(
            title="Set message content",
            label="Content",
            default=self.msg_cfg["content"],
        )
        await interaction.response.send_modal(modal)
        await modal.wait()
        self.msg_cfg["content"] = modal.text.value
        await self.update_message(interaction)

    @ui.button(label="Footer", row=1)
    async def edit_footer(self, interaction: Interaction, button):
        modal = ShortTextModal(
            title="Set message footer",
            label="Footer (Optional)",
            default=self.msg_cfg["footer"],
            required=False,
        )
        await interaction.response.send_modal(modal)
        await modal.wait()
        self.msg_cfg["footer"] = modal.text.value
        await self.update_message(interaction)

    @ui.button(label="Color", row=1)
    async def set_color(self, interaction: Interaction, button):
        modal = ShortTextModal(
            title="Set border color",
            label="Color (Optional)",
            default=self.msg_cfg["color"],
            required=False,
        )
        await interaction.response.send_modal(modal)
        await modal.wait()
        if color := modal.text.value:
            # 检查颜色格式是否正确
            try:
                if not color.startswith(("#", "0x", "rgb")):
                    color = "#" + color
                discord.Color.from_str(color)
            except ValueError:
                await interaction.followup.send(
                    embed=fail("Invalid color format"),
                    ephemeral=True,
                )
                return
        self.msg_cfg["color"] = color
        await self.update_message(interaction)

    @ui.button(label="Image", row=1)
    async def set_image(self, interaction: Interaction, button):
        modal = ShortTextModal(
            title="Set image url",
            label="Image url (Optional)",
            default=self.msg_cfg["image"],
            required=False,
        )
        await interaction.response.send_modal(modal)
        await modal.wait()
        old_image = self.msg_cfg["image"]
        try:
            self.msg_cfg["image"] = modal.text.value
            await self.update_message(interaction)
        except discord.HTTPException as ex:
            if ex.status == 400:
                # url格式错误
                self.msg_cfg["image"] = old_image
                await interaction.followup.send(
                    embed=fail("Invalid url format"),
                    ephemeral=True,
                )
            else:
                raise ex

    @ui.button(label="Help", emoji="❔", style=ButtonStyle.primary, row=2)
    async def show_help(self, interaction: Interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        color_help = (
            "## Color How-to\n"
            "Click the **Color Picker** button, pick your color, and use the color value.\n"
            "Supported color format:\n"
            "-# - `HEX`\n-# - `#HEX`\n-# - `0xHEX`\n-# - `rgb(RED, GREEN, BLUE)`"
        )
        var_help = await VarParser.get_help()
        await interaction.followup.send(
            content="\n".join([color_help, var_help]),
        )

    @ui.button(label="Save", style=ButtonStyle.success, row=3)
    async def save(self, interaction: Interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild: discord.Guild = interaction.guild  # type: ignore
        try:
            await remote_config.merge_json(
                Welcome._WELCOME_KEY, guild.id, "message", value=self.msg_cfg
            )
            embed = success("Welcome message saved")
            if not guild.system_channel:
                # 提示设置系统消息频道
                embed.color = discord.Color.orange()
                embed.description = (
                    "### Warning\n"
                    "You need to select a system channel to make this work.\n"
                    "> Settings > Engagement (or Overview on mobile) > System Message Channel"
                )
            await interaction.followup.send(embed=embed)
        except Exception as ex:
            await interaction.followup.send(embed=fail("Error while saving", ex))


class WelcomeRolesView(AutoDisableView):
    def __init__(self, *, default_roles: list[discord.Role] = []):
        super().__init__(timeout=300)
        self.select_roles.default_values = default_roles

    @ui.select(
        cls=ui.RoleSelect,
        placeholder="Select default roles...",
        min_values=0,
        max_values=25,
    )
    async def select_roles(self, interaction: Interaction, select: ui.RoleSelect):
        await interaction.response.defer()
        roles = select.values
        roles = [r for r in roles if not r.is_assignable()]
        if roles:
            mentions = " ".join([r.mention for r in roles])
            await interaction.followup.send(
                embed=fail(
                    "Invalid roles",
                    "These roles aren't assignable:\n" + mentions,
                ),
                ephemeral=True,
            )

    @ui.button(label="Save", style=ButtonStyle.success)
    async def save(self, interaction: Interaction, button):
        await interaction.response.defer(ephemeral=True, thinking=True)
        guild: discord.Guild = interaction.guild  # type: ignore
        roles = self.select_roles.values
        valid = [r for r in roles if r.is_assignable()]
        invalid = [r for r in roles if not r.is_assignable()]
        try:
            await remote_config.merge_json(
                Welcome._WELCOME_KEY,
                guild.id,
                "roles",
                value=[str(r.id) for r in valid],
            )
            msg = "Current roles:\n"
            msg += " ".join([r.mention for r in valid]) or "**None**"
            if invalid:
                msg += "\nRemoved unassignable roles:\n"
                msg += " ".join([r.mention for r in invalid])
            await interaction.followup.send(embed=success("Default roles saved", msg))
        except Exception as ex:
            await interaction.followup.send(embed=fail("Error while saving", ex))


async def setup(bot: SkyM8):
    await bot.add_cog(Welcome(bot))
