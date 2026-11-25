#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
GUR - Gunsmith Utility & Reconfigurator
=======================================
A small dark-themed tkinter editor for the GUR patch files:

    updated_mod/Stalker2/Content/GameLite/GameData/WeaponData/
        CharacterWeaponSettingsPrototypes.cfg
        WeaponGeneralSetupPrototypes.cfg

The game only ships binarized *.cfg.bin prototypes for weapon data, so
*.cfg_patch_* files next to them are ignored. For binarized prototypes the
loader applies plain *.cfg files sitting in the same folder as the prototype
as patches (ZoneKit KB 145).

Edits are line based: only the values you change are rewritten, so comments,
indentation and everything the tool does not model stay byte-identical.
Floats are always written with a dot.

The interface is bilingual (English / Ukrainian). The selected language is
stored in GUR.settings and restored on the next launch.

Usage:
    python GUR_WeaponEditor.py             # GUI
    python GUR_WeaponEditor.py --lang uk   # GUI forced to Ukrainian
    python GUR_WeaponEditor.py --selftest  # parser/save self-test
    python GUR_WeaponEditor.py --smoke     # build UI for 0.5s and exit
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

if getattr(sys, "frozen", False):
    ROOT = os.path.dirname(os.path.abspath(sys.executable))
else:
    ROOT = os.path.dirname(os.path.abspath(__file__))
UPDATED_DIR = os.path.join(ROOT, "updated_mod")
GAMEDATA_DIR = os.path.join(
    UPDATED_DIR, "Stalker2", "Content", "GameLite", "GameData", "WeaponData"
)
PLAYER_CFG = os.path.join(GAMEDATA_DIR, "CharacterWeaponSettingsPrototypes.cfg")
GS_CFG = os.path.join(GAMEDATA_DIR, "WeaponGeneralSetupPrototypes.cfg")
PAK_NAME = "GUR_WeaponReconfigurator_P.pak"
PAK_PATH = os.path.join(ROOT, PAK_NAME)
PAK_ENTRY = os.path.relpath(PLAYER_CFG, UPDATED_DIR).replace(os.sep, "/")
LEGACY_PAK_NAMES = ("StalkerWeaponEditor2_P.pak", "StalkerWeaponEditor.pak")
SETTINGS_PATH = os.path.join(ROOT, "GUR.settings")
LEGACY_SETTINGS_PATHS = (
    os.path.join(ROOT, "Stalker2_WeaponEditor.settings"),
    os.path.join(ROOT, "Stalker2_WeaponEditor.settings.json"),
)

def _find_data_file(name: str) -> str:
    for folder in (os.path.join(ROOT, "_work"), os.path.join(ROOT, "data")):
        path = os.path.join(folder, name)
        if os.path.exists(path):
            return path
    return os.path.join(ROOT, "data", name)


VANILLA_CHAR = _find_data_file("vanilla_char.cfg")
VANILLA_GS = _find_data_file("vanilla_gs.cfg")

# --- theme -----------------------------------------------------------------
BG = "#14171c"
PANEL = "#1b2027"
PANE2 = "#222a34"
FIELD = "#0e1216"
FG = "#e8e6e3"
MUTED = "#98a2b3"
ACCENT = "#d0a84c"
BORDER = "#333c48"
SEL = "#3a4654"
INK = "#17140a"

# --- editable data ---------------------------------------------------------
PLAYER_FIELDS = [
    "BaseDamage",
    "ArmorPiercing",
    "EffectiveFireDistanceMin",
    "EffectiveFireDistanceMax",
    "DispersionRadius",
    "DurabilityDamagePerShot",
    "Accuracy",
]

# Inventory bars are never edited by hand: they are derived from the real
# stats on every save (see compute_ui_values) and only written to the file.
AUTO_UI_FIELDS = ("DamageUI", "AccuracyUI", "RangeUI")
UI_BASELINE_FIELDS = (
    "BaseDamage",
    "DispersionRadius",
    "EffectiveFireDistanceMax",
    "DamageUI",
    "AccuracyUI",
    "RangeUI",
)

FIRE_TYPES = ["SemiAutomatic", "Automatic", "Queue"]
AMMO_TYPES = ["Default", "ArmorPiercing", "Supersonic", "Expanding"]

CALIBERS = [
    "EAmmoCaliber::A012",
    "EAmmoCaliber::A045",
    "EAmmoCaliber::A545",
    "EAmmoCaliber::A556",
    "EAmmoCaliber::A762",
    "EAmmoCaliber::A762NATO",
    "EAmmoCaliber::A762Sniper",
    "EAmmoCaliber::A918",
    "EAmmoCaliber::A919",
    "EAmmoCaliber::A939",
    "EAmmoCaliber::AGA",
    "EAmmoCaliber::AHEDP",
    "EAmmoCaliber::APG7V",
    "EAmmoCaliber::AVOG",
]

DEFAULT_FIRE_TYPES = ["EFireType::SemiAutomatic", "EFireType::Automatic", "EFireType::Queue"]

FRIENDLY_BASES = {
    "GunM16_ST",
    "Gun_SkifGun_HG",
    "Gun_Sharpshooter_AR",
    "Gun_Drowned_AR",
    "GunAK74_ST",
}

# Extra lowercase search words so in-game display names find the technical SIDs.
SEARCH_ALIASES = {
    "GunM16_ST": ("AR416", "M16A2"),
    "Gun_SkifGun_HG": ("Skif", "Skif's pistol", "PTM", "Скіф"),
    "Gun_Sharpshooter_AR": ("Varta", "Варта"),
    "Gun_Drowned_AR": ("Utoplenyk", "Утопленик"),
    "GunAK74_ST": ("AK74", "AKM74", "АКМ-74С"),
}

OWNER_KEYS = ["all", "player", "npc"]
CATEGORY_KEYS = ["all", "ar", "hg", "smg", "sg", "sr", "mg", "special"]
SORT_KEYS = ["alpha", "modified", "sid"]

LANG_NAMES = {"en": "English", "uk": "Українська"}
LANGUAGE_CODES = {v: k for k, v in LANG_NAMES.items()}

# ---------------------------------------------------------------------------
# Translations
# ---------------------------------------------------------------------------
TRANSLATIONS: dict[str, dict[str, str]] = {
    "en": {
        "app_title": "GUR — Gunsmith Utility & Reconfigurator (S.T.A.L.K.E.R. 2)",
        "sidebar_title": "GUR",
        "sidebar_subtitle": "Gunsmith Utility & Reconfigurator  //  patch 2.0.x",
        "weapons_header": "ALL PLAYER WEAPONS",
        "search_label": "Search:",
        "tip_search": "Filter by friendly name or technical SID (e.g. M16, AR416, GunM16).",
        "flt_owner_all": "All",
        "flt_owner_player": "Player only",
        "flt_owner_npc": "NPC only",
        "flt_cat_all": "All types",
        "flt_cat_ar": "Assault rifles",
        "flt_cat_hg": "Pistols",
        "flt_cat_smg": "Submachine guns",
        "flt_cat_sg": "Shotguns",
        "flt_cat_sr": "Sniper / marksman",
        "flt_cat_mg": "Machine guns",
        "flt_cat_special": "Special / launchers",
        "sort_alpha": "Alphabetical (A-Z)",
        "sort_modified": "Modified first",
        "sort_sid": "By SID",
        "tip_owner": "Filter by target owner (Player / NPC).",
        "tip_cat": "Filter by weapon category.",
        "tip_sort": "Sort the weapon list.",
        "view_count": "{shown} of {total} shown",
        "btn_add_vanilla": "Add ammo/recoil setup (gs)",
        "btn_reload": "Reload patch files",
        "btn_reset": "Reset to Vanilla (Remove Patch)",
        "tip_reset": "Delete this weapon's patch blocks so it uses 100% vanilla stats.",
        "select_weapon": "Select a weapon",
        "group_player": "Player stats  //  CharacterWeaponSettingsPrototypes",
        "group_gs": "General setup  //  WeaponGeneralSetupPrototypes",
        "group_notes": "Notes",
        "notes_text": (
            "Every player weapon is listed. Edit any of them - a weapon is written\n"
            "to the {{bpatch}} patch only when it differs from vanilla, so untouched\n"
            "weapons keep the game's own data. Inventory bars are computed from\n"
            "damage, dispersion and effective range automatically on save."
        ),
        "no_player_block": "No Player patch block for this weapon.",
        "no_gs_block": "No General setup patch block for this weapon.",
        "label_language": "Language:",
        "mods_folder": "Game ~mods folder:",
        "browse": "Browse…",
        "save_cfg": "Save .cfg only",
        "save_pack": "Save & Pack to .pak",
        "shortcut_hint": "Ctrl+S packs, Ctrl+Shift+S saves only",
        "status_ready": "Ready.",
        "status_unsaved": "Unsaved changes",
        "status_loaded": "Loaded {count} player weapons (vanilla + patch).",
        "status_load_failed": "Failed to load patch files",
        "status_added": "Added {sid} from vanilla (unsaved).",
        "status_reset": "Removed patch blocks for {sid} - {name} is vanilla again.",
        "sid_player": "Player",
        "sid_gs": "GS",
        "sid_vanilla": "vanilla, no patch block yet",
        # player stats
        "field_BaseDamage": "Base damage",
        "field_ArmorPiercing": "Armor piercing",
        "field_EffectiveFireDistanceMin": "Effective fire distance (min)",
        "field_EffectiveFireDistanceMax": "Effective fire distance (max)",
        "field_DispersionRadius": "Dispersion radius",
        "field_DurabilityDamagePerShot": "Durability damage per shot",
        "field_Accuracy": "Accuracy",
        "field_AccuracyUI": "Accuracy (UI, auto)",
        "field_DamageUI": "Damage (UI, auto)",
        "field_RangeUI": "Range (UI, auto)",
        "always_pierce": "Always pierce",
        "enabled": "enabled",
        # general setup
        "gs_maxammo": "Magazine capacity (MaxAmmo)",
        "gs_recoil": "Recoil radius (RecoilRadius)",
        "gs_deftype": "Default fire type (DefaultFireType)",
        "gs_firetypes": "Fire types (FireTypes)",
        "gs_caliber": "Caliber (AmmoCaliber)",
        "gs_proj_header": "Ammo overrides  (tick to include, enter projectile SID)",
        "fire_SemiAutomatic": "SemiAutomatic",
        "fire_Automatic": "Automatic",
        "fire_Queue": "Queue",
        "ammo_Default": "Default",
        "ammo_ArmorPiercing": "ArmorPiercing",
        "ammo_Supersonic": "Supersonic",
        "ammo_Expanding": "Expanding",
        # friendly weapon names
        "weapon.GunM16_ST": "M16",
        "weapon.Gun_SkifGun_HG": "Skif's Pistol",
        "weapon.Gun_Sharpshooter_AR": "Sharpshooter",
        "weapon.Gun_Drowned_AR": "Drowned",
        "weapon.GunAK74_ST": "AKM-74S",
        # tooltips
        "tip_add": "Add a General setup {{bpatch}} block (ammo, recoil, caliber) for this weapon.",
        "tip_reload": "Re-read the patch files from disk.",
        "tip_pack": "Save both .cfg files and repack GUR_WeaponReconfigurator_P.pak.",
        "tip_lang": "Interface language. Saved automatically.",
        "tip_mods": "Optional: copy the packed mod straight into the game's ~mods folder.",
        # validation
        "err_number": "{weapon}: {field} = {value} is not a number",
        "err_integer": "{weapon}: {field} = {value} is not an integer",
        "err_caliber_empty": "{weapon}: AmmoCaliber is empty",
        "err_no_firetypes": "{weapon}: no fire types selected",
        "err_proj_empty": "{weapon}: projectile SID for {ammo} is empty",
        "err_no_ammo": "{weapon}: no ammo types selected",
        # dialogs
        "dlg_reload_title": "Discard changes?",
        "dlg_reload_msg": "Reload the patch files and discard unsaved edits?",
        "dlg_load_failed_title": "Load failed",
        "dlg_load_failed_msg": "{error}\n\nExpected files:\n{files}",
        "dlg_invalid_title": "Invalid values",
        "dlg_invalid_msg": "Fix these values before saving:\n\n{errors}",
        "dlg_invalid_first": "Fix these values first:\n\n{errors}",
        "dlg_save_failed": "Save failed",
        "dlg_saved_title": "Saved",
        "dlg_saved_msg": (
            "CFG patch files saved:\n\n{player}\n{gs}\n\n"
            "Not applied in game yet - press Save & Pack to .pak to rebuild the pak."
        ),
        "dlg_repak_missing_title": "repak.exe not found",
        "dlg_repak_missing_msg": (
            "The .cfg files were saved, but repak.exe was not found.\n\n"
            "Place repak.exe next to GUR_WeaponEditor.py or in updated_mod\\ "
            "and press Save & Pack again."
        ),
        "dlg_pack_failed_title": "Packing failed",
        "dlg_pack_failed_msg": "{error}\n\nThe .cfg files were saved successfully.",
        "dlg_pack_ok_title": "Pack complete",
        "pack_ok": "Mod packed successfully.",
        "pack_archive": "Archive:  {path}",
        "pack_entries": "Entries:  {total} ({cfgs} cfg)",
        "pack_deployed": "Deployed: {path}",
        "pack_command": "Command: repak pack <clean staging copy> {name}",
        "pack_verified": "Deployed pak verified (sha256 {hash}).",
        "pack_shadow_disabled": "Disabled duplicate pak: {path}",
        "pack_shadow_other": (
            "Note: {path} also ships this patch file - the mod the game loads "
            "last wins."
        ),
        "pack_missing_folder": "Missing folder:\n{path}",
        "pack_copy_error": "\n\nCould not copy to ~mods: {error}",
        "browse_title": "Select Stalker2/Content/Paks/~mods",
        "dlg_vanilla_missing_title": "Vanilla data not found",
        "dlg_vanilla_missing_msg": (
            "Could not find:\n{missing}\n\nExtract the 2.0 cfg.bin files to "
            "data\\vanilla_char.cfg and data\\vanilla_gs.cfg first."
        ),
        "dlg_already_title": "Already present",
        "dlg_already_msg": "{sid} (base {base}) is already in the patch.",
        "dlg_notfound_title": "Not found",
        "dlg_notfound_msg": "{sid} is no longer in {path}.",
        "dlg_update_failed": "Update failed",
        "dlg_quit_title": "Unsaved changes",
        "dlg_quit_msg": "Quit without saving your edits?",
        "dlg_reset_title": "Reset to vanilla",
        "dlg_reset_msg": (
            "Remove all patch blocks for {name} ({sid})?\n\n"
            "The weapon will use 100% vanilla stats again. "
            "Unsaved edits to other weapons will be saved first."
        ),
        # add dialog
        "add_title": "Add weapon from vanilla 2.0 data",
        "add_search": "Search name or SID",
        "add_count": "{count} sections found{extra}",
        "add_showing": "  (showing first {shown})",
        "add_kind_player": "player",
        "add_kind_gs": "gs",
        "add_cancel": "Cancel",
        "add_ok": "Add weapon",
        "add_none_title": "No selection",
        "add_none_msg": "Pick a weapon section first.",
    },
    "uk": {
        "app_title": "GUR — Gunsmith Utility & Reconfigurator | Редактор зброї (S.T.A.L.K.E.R. 2)",
        "sidebar_title": "GUR",
        "sidebar_subtitle": "Gunsmith Utility & Reconfigurator  //  патч 2.0.x",
        "weapons_header": "УСЯ ЗБРОЯ ГРАВЦЯ",
        "search_label": "Пошук:",
        "tip_search": "Фільтр за назвою або технічним SID (напр. M16, AR416, GunM16).",
        "flt_owner_all": "Усі",
        "flt_owner_player": "Тільки гравець",
        "flt_owner_npc": "Тільки НПС",
        "flt_cat_all": "Усі види",
        "flt_cat_ar": "Штурмові гвинтівки",
        "flt_cat_hg": "Пістолети",
        "flt_cat_smg": "Пістолети-кулемети",
        "flt_cat_sg": "Дробовики",
        "flt_cat_sr": "Снайперські гвинтівки",
        "flt_cat_mg": "Кулемети",
        "flt_cat_special": "Спеціальна / Гранатомети",
        "sort_alpha": "За алфавітом (А-Я)",
        "sort_modified": "Спочатку змінені",
        "sort_sid": "За кодом",
        "tip_owner": "Фільтр за власником (гравець / НПС).",
        "tip_cat": "Фільтр за категорією зброї.",
        "tip_sort": "Порядок сортування списку.",
        "view_count": "Показано {shown} з {total}",
        "btn_add_vanilla": "Додати налаштування набоїв (gs)",
        "btn_reload": "Перезавантажити файли патча",
        "btn_reset": "Скинути до ванілу (Видалити патч)",
        "tip_reset": "Видалити блоки патча цієї зброї, щоб повернути 100% ванільні характеристики.",
        "select_weapon": "Виберіть зброю",
        "group_player": "Характеристики гравця  //  CharacterWeaponSettingsPrototypes",
        "group_gs": "Загальні налаштування  //  WeaponGeneralSetupPrototypes",
        "group_notes": "Примітки",
        "notes_text": (
            "Показано всю зброю гравця. Редагуйте будь-яку — до {{bpatch}}-патча\n"
            "потрапляє лише те, що відрізняється від ванілу, тож незмінені\n"
            "значення залишаються як у грі. Смуги в інвентарі рахуються\n"
            "з шкоди, розкиду та дальності автоматично під час збереження."
        ),
        "no_player_block": "Для цієї зброї немає блоку Player у патчі.",
        "no_gs_block": "Для цієї зброї немає блоку General setup у патчі.",
        "label_language": "Мова:",
        "mods_folder": "Тека ~mods гри:",
        "browse": "Огляд…",
        "save_cfg": "Зберегти лише .cfg",
        "save_pack": "Зберегти та запакувати в .pak",
        "shortcut_hint": "Ctrl+S — пакування, Ctrl+Shift+S — лише збереження",
        "status_ready": "Готово.",
        "status_unsaved": "Незбережені зміни",
        "status_loaded": "Завантажено зброї гравця: {count} (ваніль + патч).",
        "status_load_failed": "Не вдалося завантажити файли патча",
        "status_added": "Додано {sid} з ванілі (не збережено).",
        "status_reset": "Блоки патча для {sid} видалено — {name} знову ванільна.",
        "sid_player": "Гравець",
        "sid_gs": "Загальні",
        "sid_vanilla": "ваніль, блоку патча ще немає",
        # player stats
        "field_BaseDamage": "Базова шкода (BaseDamage)",
        "field_ArmorPiercing": "Пробиття броні (ArmorPiercing)",
        "field_EffectiveFireDistanceMin": "Ефективна дальність, мін. (EffectiveFireDistanceMin)",
        "field_EffectiveFireDistanceMax": "Ефективна дальність, макс. (EffectiveFireDistanceMax)",
        "field_DispersionRadius": "Розкид куль (DispersionRadius)",
        "field_DurabilityDamagePerShot": "Знос за постріл (DurabilityDamagePerShot)",
        "field_Accuracy": "Точність (Accuracy)",
        "field_AccuracyUI": "Точність в інтерфейсі (авто)",
        "field_DamageUI": "Шкода в інтерфейсі (авто)",
        "field_RangeUI": "Дальність в інтерфейсі (авто)",
        "always_pierce": "Завжди пробиває",
        "enabled": "увімкнено",
        # general setup
        "gs_maxammo": "Розмір магазина (MaxAmmo)",
        "gs_recoil": "Сила віддачі (RecoilRadius)",
        "gs_deftype": "Тип вогню за замовчуванням (DefaultFireType)",
        "gs_firetypes": "Режими вогню (FireTypes)",
        "gs_caliber": "Калібр (AmmoCaliber)",
        "gs_proj_header": "Перевизначення набоїв (позначте потрібні, вкажіть SID снаряда)",
        "fire_SemiAutomatic": "Напівавтоматичний",
        "fire_Automatic": "Автоматичний",
        "fire_Queue": "Черга",
        "ammo_Default": "Звичайний",
        "ammo_ArmorPiercing": "Бронебійний",
        "ammo_Supersonic": "Надзвуковий",
        "ammo_Expanding": "Експансивний",
        # friendly weapon names
        "weapon.GunM16_ST": "M16",
        "weapon.Gun_SkifGun_HG": "Пістолет Скіфа / Skif's Pistol",
        "weapon.Gun_Sharpshooter_AR": "Варта / Sharpshooter",
        "weapon.Gun_Drowned_AR": "Утопленик / Drowned",
        "weapon.GunAK74_ST": "АКМ-74С / AKM-74S",
        # tooltips
        "tip_add": "Додати блок {{bpatch}} загальних налаштувань (набої, віддача, калібр) для цієї зброї.",
        "tip_reload": "Перечитати файли патча з диска.",
        "tip_pack": "Зберегти обидва .cfg і перепакувати GUR_WeaponReconfigurator_P.pak.",
        "tip_lang": "Мова інтерфейсу. Зберігається автоматично.",
        "tip_mods": "Необов'язково: копіювати запакований мод одразу в теку ~mods гри.",
        # validation
        "err_number": "{weapon}: {field} = {value} — не число",
        "err_integer": "{weapon}: {field} = {value} — не ціле число",
        "err_caliber_empty": "{weapon}: AmmoCaliber порожній",
        "err_no_firetypes": "{weapon}: не вибрано жодного режиму вогню",
        "err_proj_empty": "{weapon}: SID снаряда для {ammo} порожній",
        "err_no_ammo": "{weapon}: не вибрано жодного типу набоїв",
        # dialogs
        "dlg_reload_title": "Скасувати зміни?",
        "dlg_reload_msg": "Перезавантажити файли патча та скасувати незбережені зміни?",
        "dlg_load_failed_title": "Не вдалося завантажити",
        "dlg_load_failed_msg": "{error}\n\nОчікувані файли:\n{files}",
        "dlg_invalid_title": "Некоректні значення",
        "dlg_invalid_msg": "Виправте ці значення перед збереженням:\n\n{errors}",
        "dlg_invalid_first": "Спочатку виправте ці значення:\n\n{errors}",
        "dlg_save_failed": "Не вдалося зберегти",
        "dlg_saved_title": "Збережено",
        "dlg_saved_msg": (
            "Файли патча .cfg збережено:\n\n{player}\n{gs}\n\n"
            "У грі вони ще не діють — натисніть «Зберегти та запакувати в .pak»."
        ),
        "dlg_repak_missing_title": "repak.exe не знайдено",
        "dlg_repak_missing_msg": (
            "Файли .cfg збережено, але repak.exe не знайдено.\n\n"
            "Покладіть repak.exe поруч зі GUR_WeaponEditor.py або в updated_mod\\ "
            "і натисніть «Зберегти та запакувати» ще раз."
        ),
        "dlg_pack_failed_title": "Не вдалося запакувати",
        "dlg_pack_failed_msg": "{error}\n\nФайли .cfg успішно збережено.",
        "dlg_pack_ok_title": "Пакування завершено",
        "pack_ok": "Мод успішно запаковано.",
        "pack_archive": "Архів:  {path}",
        "pack_entries": "Файлів:  {total} ({cfgs} cfg)",
        "pack_deployed": "Скопійовано: {path}",
        "pack_command": "Команда: repak pack <чиста копія> {name}",
        "pack_verified": "Розгорнутий pak перевірено (sha256 {hash}).",
        "pack_shadow_disabled": "Вимкнено дубль pak: {path}",
        "pack_shadow_other": (
            "Увага: {path} теж містить цей файл патча — перемагає мод, "
            "який гра завантажить останнім."
        ),
        "pack_missing_folder": "Немає теки:\n{path}",
        "pack_copy_error": "\n\nНе вдалося скопіювати в ~mods: {error}",
        "browse_title": "Виберіть теку Stalker2/Content/Paks/~mods",
        "dlg_vanilla_missing_title": "Ванільні дані не знайдено",
        "dlg_vanilla_missing_msg": (
            "Не знайдено:\n{missing}\n\nСпочатку розпакуйте cfg.bin файли 2.0 у "
            "data\\vanilla_char.cfg та data\\vanilla_gs.cfg."
        ),
        "dlg_already_title": "Уже присутня",
        "dlg_already_msg": "{sid} (база {base}) уже є в патчі.",
        "dlg_notfound_title": "Не знайдено",
        "dlg_notfound_msg": "{sid} більше немає у {path}.",
        "dlg_update_failed": "Не вдалося оновити",
        "dlg_quit_title": "Незбережені зміни",
        "dlg_quit_msg": "Вийти без збереження змін?",
        "dlg_reset_title": "Скинути до ванілу",
        "dlg_reset_msg": (
            "Видалити всі блоки патча для {name} ({sid})?\n\n"
            "Зброя знову матиме 100% ванільні характеристики. "
            "Незбережені зміни іншої зброї буде спершу збережено."
        ),
        # add dialog
        "add_title": "Додати зброю з ванільних даних 2.0",
        "add_search": "Пошук назви або SID",
        "add_count": "Знайдено розділів: {count}{extra}",
        "add_showing": "  (показано перші {shown})",
        "add_kind_player": "гравець",
        "add_kind_gs": "загальні",
        "add_cancel": "Скасувати",
        "add_ok": "Додати зброю",
        "add_none_title": "Нічого не вибрано",
        "add_none_msg": "Спочатку виберіть розділ зброї.",
    },
}


def translate(lang: str, key: str, **kwargs) -> str:
    text = TRANSLATIONS.get(lang, {}).get(key)
    if text is None:
        text = TRANSLATIONS["en"].get(key, key)
    try:
        return text.format(**kwargs)
    except (KeyError, IndexError, ValueError):
        return text


_HEADER_RE = re.compile(r"^([A-Za-z0-9_.]+)\s*:\s*struct\.begin\b")


class EditorError(Exception):
    pass


# ---------------------------------------------------------------------------
# CFG engine
# ---------------------------------------------------------------------------
class CfgDoc:
    """Line-preserving .cfg document."""

    def __init__(self, path: str):
        self.path = path
        with open(path, "rb") as fh:
            raw = fh.read()
        self.bom = raw.startswith(b"\xef\xbb\xbf")
        text = raw.decode("utf-8-sig")
        self.eol = "\r\n" if "\r\n" in text else "\n"
        self.lines = text.replace("\r\n", "\n").split("\n")

    def save(self, path: str | None = None) -> None:
        path = path or self.path
        data = self.eol.join(self.lines).encode("utf-8")
        if self.bom:
            data = b"\xef\xbb\xbf" + data
        with open(path, "wb") as fh:
            fh.write(data)

    def sections(self) -> list["Section"]:
        out: list[Section] = []
        lines = self.lines
        n = len(lines)
        i = 0
        while i < n:
            match = _HEADER_RE.match(lines[i])
            if not match:
                i += 1
                continue
            depth = 0
            j = i
            while j < n:
                depth += lines[j].count("struct.begin") - lines[j].count("struct.end")
                if depth == 0:
                    break
                j += 1
            out.append(Section(self, match.group(1), i, min(j, n - 1)))
            i = j + 1
        return out


class Section:
    __slots__ = ("doc", "name", "start", "end")

    def __init__(self, doc: CfgDoc, name: str, start: int, end: int):
        self.doc = doc
        self.name = name
        self.start = start
        self.end = end

    def find_scalar(self, name: str, within: tuple[int, int] | None = None):
        """Return (line_index, indent, value) of the first `name = value` line."""
        s, e = within if within else (self.start, self.end)
        pat = re.compile(r"^(\s*)" + re.escape(name) + r"\s*=\s*(.*?)\s*$")
        for i in range(s + 1, e):
            line = self.doc.lines[i]
            if line.lstrip().startswith("//"):
                continue
            match = pat.match(line)
            if match:
                return i, match.group(1), match.group(2)
        return None

    def find_struct(self, name: str, within: tuple[int, int] | None = None):
        """Return (first_line, last_line) of a nested `name : struct.begin` block."""
        s, e = within if within else (self.start, self.end)
        pat = re.compile(r"^(\s*)" + re.escape(name) + r"\s*:\s*struct\.begin\b")
        for i in range(s + 1, e):
            if not pat.match(self.doc.lines[i]):
                continue
            depth = 0
            for j in range(i, e):
                depth += self.doc.lines[j].count("struct.begin") - self.doc.lines[j].count("struct.end")
                if depth == 0:
                    return i, j
        return None


def parse_fire_types(doc: CfgDoc, span: tuple[int, int]) -> list[str]:
    out = []
    pat = re.compile(r"^\s*\[\d+\]\s*=\s*EFireType::(\w+)")
    for i in range(span[0], span[1] + 1):
        match = pat.match(doc.lines[i])
        if match:
            out.append(match.group(1))
    return out


def parse_projectiles(doc: CfgDoc, span: tuple[int, int]) -> list[list[str]]:
    out: list[list[str]] = []
    pat_ammo = re.compile(r"^\s*AmmoType\s*=\s*EAmmoType::(\w+)")
    pat_proj = re.compile(r"^\s*ProjectilePrototypeSID\s*=\s*(\S+)")
    ammo = None
    for i in range(span[0], span[1] + 1):
        match = pat_ammo.match(doc.lines[i])
        if match:
            ammo = match.group(1)
            continue
        match = pat_proj.match(doc.lines[i])
        if match and ammo:
            out.append([ammo, match.group(1)])
            ammo = None
    return out


def build_fire_types(indent: str, types: list[str]) -> list[str]:
    out = [indent + "FireTypes : struct.begin {bskipref}"]
    for idx, ftype in enumerate(types):
        out.append(f"{indent}   [{idx}] = EFireType::{ftype}")
    out.append(indent + "struct.end")
    return out


def build_projectiles(indent: str, items: list[list[str]]) -> list[str]:
    out = [indent + "AmmoTypeProjectiles : struct.begin {bskipref}"]
    for idx, (ammo, proj) in enumerate(items):
        out += [
            f"{indent}   [{idx}] : struct.begin",
            f"{indent}      AmmoType = EAmmoType::{ammo}",
            f"{indent}      ProjectilePrototypeSID = {proj}",
            f"{indent}   struct.end",
        ]
    out.append(indent + "struct.end")
    return out


def apply_replacements(doc: CfgDoc, reps: list[tuple[int, int, list[str]]]) -> None:
    for start, end, new_lines in sorted(reps, key=lambda r: r[0], reverse=True):
        doc.lines[start:end] = new_lines


def _add_scalar(doc, sec, name, value, reps, within=None) -> bool:
    found = sec.find_scalar(name, within=within)
    if not found:
        return False
    idx, indent, _old = found
    reps.append((idx, idx + 1, [indent + name + " = " + value]))
    return True


def _add_recoil(doc, sec, value, reps) -> bool:
    span = sec.find_struct("RecoilParams")
    if not span:
        return False
    return _add_scalar(doc, sec, "RecoilRadius", value, reps, within=span)


def _add_fire_types(doc, sec, types, reps) -> bool:
    span = sec.find_struct("FireTypes")
    if not span:
        return False
    indent = re.match(r"^(\s*)", doc.lines[span[0]]).group(1)
    reps.append((span[0], span[1] + 1, build_fire_types(indent, types)))
    return True


def _add_projectiles(doc, sec, items, reps) -> bool:
    span = sec.find_struct("AmmoTypeProjectiles")
    if not span:
        return False
    indent = re.match(r"^(\s*)", doc.lines[span[0]]).group(1)
    reps.append((span[0], span[1] + 1, build_projectiles(indent, items)))
    return True


def append_block(doc: CfgDoc, block: list[str]) -> None:
    while doc.lines and doc.lines[-1] == "":
        doc.lines.pop()
    doc.lines.append("")
    doc.lines.extend(block)
    doc.lines.append("")


def remove_section(doc: CfgDoc, name: str) -> bool:
    """Delete a top-level section block, keeping the surrounding layout tidy."""
    for sec in doc.sections():
        if sec.name != name:
            continue
        start, end = sec.start, sec.end
        del doc.lines[start:end + 1]
        while (
            start > 0
            and start < len(doc.lines)
            and doc.lines[start] == ""
            and doc.lines[start - 1] == ""
        ):
            del doc.lines[start]
        while doc.lines and doc.lines[-1] == "":
            doc.lines.pop()
        doc.lines.append("")
        return True
    return False


def base_sid(sid: str) -> str:
    for suffix in ("_Player_WS", "_Player", "_GS"):
        if sid.endswith(suffix):
            return sid[: -len(suffix)]
    return sid


def friendly_name(base: str, lang: str = "en") -> str:
    key = "weapon." + base
    table = TRANSLATIONS.get(lang, {})
    if key in table:
        return table[key]
    if key in TRANSLATIONS["en"]:
        return TRANSLATIONS["en"][key]
    name = base
    for prefix in ("Gun_", "Gun", "EN_"):
        if name.startswith(prefix):
            name = name[len(prefix):]
            break
    return name.replace("_", " ").strip() or base


def weapon_label(weapon: "Weapon", lang: str = "en") -> str:
    names = [sec.name for sec in (weapon.player, weapon.gs) if sec is not None]
    title = friendly_name(weapon.base, lang)
    if len(names) == 2:
        return f"{title}  ({names[0]} / _GS)"
    if names:
        return f"{title}  ({names[0]})"
    return title


def fmt_float(value) -> str:
    text = str(value).strip().replace(",", ".")
    number = float(text)
    if number == int(number) and abs(number) < 1e15:
        return f"{number:.1f}"
    return repr(number)


# ---------------------------------------------------------------------------
# Inventory stat bars
# ---------------------------------------------------------------------------
_UI_BASELINE: dict[str, dict[str, str]] | None = None


def section_ui_values(sec: Section) -> dict[str, str]:
    """Values of the UI baseline fields as currently written in a section."""
    row = {}
    for key in UI_BASELINE_FIELDS:
        found = sec.find_scalar(key)
        if found:
            row[key] = found[2].strip()
    return row


def vanilla_ui_baseline() -> dict[str, dict[str, str]]:
    """Vanilla per-section stats used as the reference for UI bars."""
    global _UI_BASELINE
    if _UI_BASELINE is None or (not _UI_BASELINE and os.path.exists(VANILLA_CHAR)):
        _UI_BASELINE = {}
        try:
            doc = CfgDoc(VANILLA_CHAR)
        except Exception:
            return _UI_BASELINE
        for sec in doc.sections():
            row = section_ui_values(sec)
            if row:
                _UI_BASELINE[sec.name] = row
    return _UI_BASELINE


def _to_number(mapping, key):
    try:
        return float(str(mapping.get(key, "")).replace(",", ".").strip())
    except (TypeError, ValueError):
        return None


def compute_ui_values(
    section_name: str,
    values: dict[str, str],
    fallback: dict[str, str] | None = None,
) -> dict[str, str]:
    """Derive the inventory bars from the real stats.

    UI bars are scaled relative to a reference value of the same section, so an
    untouched weapon keeps its display and every edit moves the bar in
    proportion. Accuracy is inverse to dispersion (lower spread -> better bar).
    The reference is the vanilla dump when available; otherwise the section's
    own current file values are used, so the mapping still works on a fresh
    install without _work.
    """
    base = vanilla_ui_baseline().get(section_name) or {}
    stock = fallback or {}

    def reference(ui_key, field):
        for source in (base, stock):
            if _to_number(source, ui_key) is not None and _to_number(source, field):
                return source
        return None

    def scaled(ui_key, field, inverse=False):
        ref = reference(ui_key, field)
        if ref is None:
            return None
        ui = _to_number(ref, ui_key)
        was = _to_number(ref, field)
        now = _to_number(values, field)
        if now is None:
            return None
        if inverse:
            ratio = 1.0 if now <= 0 else was / now
        else:
            ratio = now / was
        return min(1.0, max(0.0, ui * ratio))

    out = {}
    for ui_key, field, inverse in (
        ("DamageUI", "BaseDamage", False),
        ("AccuracyUI", "DispersionRadius", True),
        ("RangeUI", "EffectiveFireDistanceMax", False),
    ):
        value = scaled(ui_key, field, inverse)
        if value is not None:
            out[ui_key] = f"{value:.2f}"
    return out


def weapon_ui_values(weapon: "Weapon", values: dict[str, str]) -> dict[str, str]:
    """Inventory bars for the given stats, scaled against the vanilla section."""
    ref = weapon.vanilla if weapon.vanilla is not None else weapon.player
    if ref is None:
        return {}
    return compute_ui_values(ref.name, values, section_ui_values(ref))


# ---------------------------------------------------------------------------
# Weapon model
# ---------------------------------------------------------------------------
class Weapon:
    def __init__(self, base: str):
        self.base = base
        self.player: Section | None = None
        self.vanilla: Section | None = None
        self.gs: Section | None = None
        self.player_is_patch = False
        self.player_values: dict[str, str] = {}
        self.player_bool: bool | None = None
        self.gs_values: dict[str, str] = {}
        self.recoil_radius: str | None = None
        self.caliber: str | None = None
        self.has_fire_types = False
        self.fire_types: list[str] = []
        self.has_projectiles = False
        self.projectiles: list[list[str]] = []
        self.loaded_sig = None


def load_weapon_values(weapon: Weapon) -> None:
    weapon.player_values = {}
    weapon.player_bool = None
    # Vanilla first, patch overrides second: every listed weapon carries the
    # full set of editable stats even when its patch block has only a few.
    for sec in (weapon.vanilla, weapon.player):
        if sec is None:
            continue
        for name in PLAYER_FIELDS:
            found = sec.find_scalar(name)
            if found:
                weapon.player_values[name] = found[2]
        found = sec.find_scalar("AlwaysPierce")
        if found:
            weapon.player_bool = found[2].strip().lower() == "true"
    if weapon.gs is not None:
        for name in ("MaxAmmo", "DefaultFireType"):
            found = weapon.gs.find_scalar(name)
            if found:
                weapon.gs_values[name] = found[2]
        found = weapon.gs.find_scalar("AmmoCaliber")
        if found:
            weapon.caliber = found[2]
        span = weapon.gs.find_struct("RecoilParams")
        if span:
            found = weapon.gs.find_scalar("RecoilRadius", within=span)
            if found:
                weapon.recoil_radius = found[2]
        span = weapon.gs.find_struct("FireTypes")
        if span:
            weapon.has_fire_types = True
            weapon.fire_types = parse_fire_types(weapon.gs.doc, span)
        span = weapon.gs.find_struct("AmmoTypeProjectiles")
        if span:
            weapon.has_projectiles = True
            weapon.projectiles = parse_projectiles(weapon.gs.doc, span)
    weapon.loaded_sig = weapon_signature(weapon)


def build_weapons(
    player_doc: CfgDoc,
    gs_doc: CfgDoc,
    vanilla_player: CfgDoc | None = None,
) -> list[Weapon]:
    weapons: dict[str, Weapon] = {}
    order: list[str] = []
    for doc, kind in ((player_doc, "player"), (gs_doc, "gs")):
        for sec in doc.sections():
            base = base_sid(sec.name)
            weapon = weapons.get(base)
            if weapon is None:
                weapon = Weapon(base)
                weapons[base] = weapon
                order.append(base)
            if kind == "player":
                weapon.player = sec
                weapon.player_is_patch = True
            else:
                weapon.gs = sec
    if vanilla_player is not None:
        for sec in vanilla_player.sections():
            if sid_owner(sec.name) != "player":
                continue
            base = base_sid(sec.name)
            weapon = weapons.get(base)
            if weapon is None:
                weapon = Weapon(base)
                weapon.player = sec
                weapons[base] = weapon
                order.append(base)
            weapon.vanilla = sec
    result = [weapons[base] for base in order]
    for weapon in result:
        load_weapon_values(weapon)
    return result


def weapon_signature(weapon: Weapon):
    return (
        tuple(sorted(weapon.player_values.items())),
        weapon.player_bool,
        tuple(sorted(weapon.gs_values.items())),
        weapon.recoil_radius,
        weapon.caliber,
        tuple(weapon.fire_types),
        tuple((ammo, proj) for ammo, proj in weapon.projectiles),
    )


def is_modified(weapon: Weapon) -> bool:
    """True when the in-memory values differ from the last load/save."""
    return weapon.loaded_sig is None or weapon_signature(weapon) != weapon.loaded_sig


def weapon_full_values(weapon: Weapon) -> dict[str, str]:
    return dict(weapon.player_values)


def _same_value(left: str, right: str) -> bool:
    try:
        return abs(float(left.replace(",", ".")) - float(right.replace(",", "."))) < 1e-6
    except (AttributeError, TypeError, ValueError):
        return (left or "").strip().casefold() == (right or "").strip().casefold()


def changed_stats(weapon: Weapon) -> bool:
    """True when the weapon differs from vanilla in any editable stat."""
    if weapon.player is None:
        return False
    if weapon.vanilla is None:
        return weapon.player_is_patch
    for name in PLAYER_FIELDS:
        current = weapon.player_values.get(name)
        if current is None:
            continue
        found = weapon.vanilla.find_scalar(name)
        if not found or not _same_value(current, found[2]):
            return True
    found = weapon.vanilla.find_scalar("AlwaysPierce")
    if found and weapon.player_bool is not None:
        if weapon.player_bool != (found[2].strip().lower() == "true"):
            return True
    return False


def sid_owner(sid: str) -> str:
    return "player" if "_player" in sid.casefold() else "npc"


def weapon_owner(weapon: Weapon) -> str:
    names = [sec.name for sec in (weapon.player, weapon.gs) if sec is not None]
    return "player" if any("_player" in name.casefold() for name in names) else "npc"


def weapon_category(base: str, sid: str = "") -> str:
    text = f"{base} {sid}".casefold()
    if any(word in text for word in ("gauss", "rpg", "grenade", "_gl", "launcher")):
        return "special"
    if "_pp" in text or "_smg" in text or "smg" in text or "viper" in text:
        return "smg"
    if any(word in text for word in (
        "_hg", "pistol", "ptm", "udp", "apsb", "gsh", "korovin", "makarov", "skif",
    )):
        return "hg"
    if any(word in text for word in ("_sg", "shotgun", "spsa", "m860", "saiga", "ram-2")):
        return "sg"
    if any(word in text for word in ("_sr", "sniper", "marksman", "_svd", "svu", "lynx")):
        return "sr"
    if "_lmg" in text or "_mg" in text or "machinegun" in text or "machine gun" in text:
        return "mg"
    if any(word in text for word in (
        "_ar", "m16", "ak74", "akm", "dnipro", "kharod", "fora", "buket", "grom", "lavina",
    )):
        return "ar"
    return "other"


def entry_search_blob(sid: str, base: str, lang: str) -> str:
    parts = [sid, base, friendly_name(base, lang)]
    parts.extend(SEARCH_ALIASES.get(base, ()))
    return " ".join(parts).casefold()


def weapon_search_blob(weapon: Weapon, lang: str) -> str:
    parts = [entry_search_blob(weapon.base, weapon.base, lang)]
    for sec in (weapon.player, weapon.gs):
        if sec is not None:
            parts.append(sec.name)
    return " ".join(parts).casefold()


def sort_weapons(items: list[Weapon], sort_key: str, lang: str) -> list[Weapon]:
    def alpha_key(weapon):
        return friendly_name(weapon.base, lang).casefold(), weapon.base.casefold()

    if sort_key == "modified":
        return sorted(items, key=lambda weapon: ((not is_modified(weapon),) + alpha_key(weapon)))
    if sort_key == "sid":
        return sorted(items, key=lambda weapon: weapon.base.casefold())
    return sorted(items, key=alpha_key)


def filter_weapons(
    weapons: list[Weapon],
    lang: str,
    query: str = "",
    owner: str = "all",
    category: str = "all",
    sort_key: str = "alpha",
) -> list[Weapon]:
    needle = query.strip().casefold()
    items = []
    for weapon in weapons:
        if needle and needle not in weapon_search_blob(weapon, lang):
            continue
        if owner != "all" and weapon_owner(weapon) != owner:
            continue
        if category != "all":
            sid = weapon.player.name if weapon.player is not None else (
                weapon.gs.name if weapon.gs is not None else ""
            )
            if weapon_category(weapon.base, sid) != category:
                continue
        items.append(weapon)
    return sort_weapons(items, sort_key, lang)


def validate_and_normalize(weapons: list[Weapon], tr=None) -> list[str]:
    if tr is None:
        tr = lambda key, **kw: translate("en", key, **kw)  # noqa: E731
    errors: list[str] = []
    for weapon in weapons:
        for name in PLAYER_FIELDS:
            if name not in weapon.player_values:
                continue
            try:
                weapon.player_values[name] = fmt_float(weapon.player_values[name])
            except ValueError:
                errors.append(tr(
                    "err_number", weapon=weapon.base, field=name,
                    value=weapon.player_values[name],
                ))
        if weapon.gs is None:
            continue
        if "MaxAmmo" in weapon.gs_values:
            try:
                weapon.gs_values["MaxAmmo"] = str(
                    int(float(weapon.gs_values["MaxAmmo"].strip().replace(",", ".")))
                )
            except ValueError:
                errors.append(tr(
                    "err_integer", weapon=weapon.base, field="MaxAmmo",
                    value=weapon.gs_values["MaxAmmo"],
                ))
        if weapon.recoil_radius is not None:
            try:
                weapon.recoil_radius = fmt_float(weapon.recoil_radius)
            except ValueError:
                errors.append(tr(
                    "err_number", weapon=weapon.base, field="RecoilRadius",
                    value=weapon.recoil_radius,
                ))
        if weapon.caliber is not None:
            value = weapon.caliber.strip()
            if not value:
                errors.append(tr("err_caliber_empty", weapon=weapon.base))
            else:
                if not value.startswith("EAmmoCaliber::"):
                    value = "EAmmoCaliber::" + value
                weapon.caliber = value
        if "DefaultFireType" in weapon.gs_values:
            value = weapon.gs_values["DefaultFireType"].strip()
            if value and not value.startswith("EFireType::"):
                value = "EFireType::" + value
            weapon.gs_values["DefaultFireType"] = value
        if weapon.has_fire_types and not weapon.fire_types:
            errors.append(tr("err_no_firetypes", weapon=weapon.base))
        if weapon.has_projectiles:
            cleaned = []
            for ammo, proj in weapon.projectiles:
                proj = proj.strip()
                if not proj:
                    errors.append(tr("err_proj_empty", weapon=weapon.base, ammo=ammo))
                else:
                    cleaned.append([ammo, proj])
            if not cleaned:
                errors.append(tr("err_no_ammo", weapon=weapon.base))
            weapon.projectiles = cleaned
    return errors


def apply_model_to_docs(weapons: list[Weapon], player_doc: CfgDoc, gs_doc: CfgDoc) -> None:
    """Rewrite the player patch file from the model.

    Every block is rebuilt, so weapons that match vanilla again lose their
    override, changed weapons (including ones that had no block yet) get a full
    {bpatch} block, and the inventory bars are written from the real stats.
    """
    sections = player_doc.sections()
    header_end = sections[0].start if sections else len(player_doc.lines)
    header = list(player_doc.lines[:header_end])
    while header and not header[-1].strip():
        header.pop()

    new_lines = header
    for weapon in weapons:
        if weapon.player is None or not changed_stats(weapon):
            continue
        values = weapon_full_values(weapon)
        ui = weapon_ui_values(weapon, values)
        if new_lines:
            new_lines.append("")
        new_lines.extend(build_player_block(weapon.player.name, values, weapon.player_bool, ui))
    new_lines.append("")
    player_doc.lines = new_lines

    gs_reps: list[tuple[int, int, list[str]]] = []
    for weapon in weapons:
        if weapon.gs is None:
            continue
        if "MaxAmmo" in weapon.gs_values:
            _add_scalar(gs_doc, weapon.gs, "MaxAmmo", weapon.gs_values["MaxAmmo"], gs_reps)
        if "DefaultFireType" in weapon.gs_values:
            _add_scalar(gs_doc, weapon.gs, "DefaultFireType", weapon.gs_values["DefaultFireType"], gs_reps)
        if weapon.caliber is not None:
            _add_scalar(gs_doc, weapon.gs, "AmmoCaliber", weapon.caliber, gs_reps)
        if weapon.recoil_radius is not None:
            _add_recoil(gs_doc, weapon.gs, weapon.recoil_radius, gs_reps)
        if weapon.has_fire_types:
            _add_fire_types(gs_doc, weapon.gs, weapon.fire_types, gs_reps)
        if weapon.has_projectiles:
            _add_projectiles(gs_doc, weapon.gs, weapon.projectiles, gs_reps)
    apply_replacements(gs_doc, gs_reps)


# ---------------------------------------------------------------------------
# Vanilla blocks
# ---------------------------------------------------------------------------
def build_player_block(
    sid: str,
    values: dict[str, str],
    pierce: bool | None = None,
    ui: dict[str, str] | None = None,
) -> list[str]:
    out = [f"{sid} : struct.begin {{bpatch}}"]
    for name in PLAYER_FIELDS:
        text = values.get(name)
        if text is not None and text.strip():
            out.append(f"   {name} = {text.strip()}")
    if pierce is not None:
        out.append(f"   AlwaysPierce = {'true' if pierce else 'false'}")
    for name in AUTO_UI_FIELDS:
        text = (ui or {}).get(name)
        if text:
            out.append(f"   {name} = {text}")
    out.append("struct.end")
    return out


def build_gs_block(vanilla_doc: CfgDoc, sec: Section) -> list[str]:
    out = [f"{sec.name} : struct.begin {{bpatch}}"]
    span = sec.find_struct("FireTypes")
    if span:
        types = parse_fire_types(vanilla_doc, span)
        if types:
            out.extend(build_fire_types("   ", types))
    span = sec.find_struct("RecoilParams")
    if span:
        found = sec.find_scalar("RecoilRadius", within=span)
        if found:
            out += [
                "   RecoilParams : struct.begin {bpatch}",
                f"      RecoilRadius = {found[2]}",
                "   struct.end",
            ]
    for name in ("MaxAmmo", "DefaultFireType", "AmmoCaliber"):
        found = sec.find_scalar(name)
        if found:
            out.append(f"   {name} = {found[2]}")
    span = sec.find_struct("AmmoTypeProjectiles")
    if span:
        items = parse_projectiles(vanilla_doc, span)
        if items:
            out.extend(build_projectiles("   ", items))
    out.append("struct.end")
    return out


# ---------------------------------------------------------------------------
# Settings / repak helpers
# ---------------------------------------------------------------------------
def read_settings() -> dict:
    for path in (SETTINGS_PATH, *LEGACY_SETTINGS_PATHS):
        try:
            with open(path, "r", encoding="utf-8") as fh:
                data = json.load(fh)
        except (OSError, ValueError):
            continue
        if isinstance(data, dict):
            if path != SETTINGS_PATH:
                write_settings(data)
            return data
    return {}


def write_settings(data: dict) -> None:
    try:
        with open(SETTINGS_PATH, "w", encoding="utf-8") as fh:
            json.dump(data, fh, indent=2, ensure_ascii=False)
    except OSError:
        pass


def find_repak() -> str | None:
    candidates = [
        os.path.join(ROOT, "repak.exe"),
        os.path.join(UPDATED_DIR, "repak.exe"),
        os.path.join(ROOT, "tools", "repak.exe"),
        os.path.join(ROOT, "_work", "tools", "repak.exe"),
    ]
    for path in candidates:
        if os.path.isfile(path):
            return path
    return shutil.which("repak")


def _run_hidden(cmd: list[str]) -> subprocess.CompletedProcess:
    flags = 0
    if os.name == "nt":
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0)
    return subprocess.run(
        cmd, capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=300, creationflags=flags,
    )


def sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def pak_entry_names(repak: str, pak_path: str) -> set[str]:
    proc = _run_hidden([repak, "list", pak_path])
    if proc.returncode != 0:
        return set()
    return {
        line.strip().replace("\\", "/").lstrip("/")
        for line in proc.stdout.splitlines()
        if line.strip()
    }


def game_paks_root(path: str) -> str | None:
    """Climb from a mods folder up to the game's .../Content/Paks folder."""
    current = os.path.normpath(path)
    while True:
        if os.path.basename(current).lower() == "paks":
            return current
        parent = os.path.dirname(current)
        if parent == current:
            return None
        current = parent


def find_shadowing_paks(
    repak: str, paks_root: str, entry: str, skip: set[str]
) -> tuple[list[str], list[str]]:
    """Paks under paks_root that also ship `entry`.

    Returns (copies named like our pak, paks of other mods).
    """
    same_name: list[str] = []
    other: list[str] = []
    skipped = {os.path.normcase(os.path.abspath(p)) for p in skip}
    for dirpath, _dirs, files in os.walk(paks_root):
        for name in files:
            if not name.lower().endswith(".pak"):
                continue
            if name.lower().startswith(("pakchunk", "global")):
                continue
            path = os.path.join(dirpath, name)
            if os.path.normcase(os.path.abspath(path)) in skipped:
                continue
            if entry in pak_entry_names(repak, path):
                if name.lower() == PAK_NAME.lower():
                    same_name.append(path)
                else:
                    other.append(path)
    return same_name, other


def disable_pak(path: str) -> str:
    """Rename a pak so the game stops mounting it; returns the new path."""
    backup = path + ".disabled"
    counter = 1
    while os.path.exists(backup):
        backup = f"{path}.{counter}.disabled"
        counter += 1
    os.rename(path, backup)
    return backup


# ---------------------------------------------------------------------------
# GUI helpers
# ---------------------------------------------------------------------------
class Tooltip:
    def __init__(self, widget, get_text, delay=450):
        self.widget = widget
        self.get_text = get_text
        self.delay = delay
        self.tip = None
        self._after = None
        widget.bind("<Enter>", self._schedule, add="+")
        widget.bind("<Leave>", self._hide, add="+")
        widget.bind("<ButtonPress>", self._hide, add="+")
        widget.bind("<Destroy>", self._hide, add="+")

    def _schedule(self, _event=None):
        self._cancel()
        try:
            self._after = self.widget.after(self.delay, self._show)
        except tk.TclError:
            pass

    def _cancel(self):
        if self._after is not None:
            try:
                self.widget.after_cancel(self._after)
            except tk.TclError:
                pass
            self._after = None

    def _show(self):
        text = self.get_text()
        if not text:
            return
        x = self.widget.winfo_rootx() + 12
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 8
        self.tip = tk.Toplevel(self.widget)
        self.tip.wm_overrideredirect(True)
        self.tip.wm_geometry(f"+{x}+{y}")
        frame = tk.Frame(
            self.tip, bg=PANEL, highlightbackground=BORDER, highlightthickness=1
        )
        frame.pack()
        tk.Label(
            frame, text=text, bg=PANEL, fg=FG, font=("Segoe UI", 9),
            justify="left", padx=8, pady=4,
        ).pack()

    def _hide(self, _event=None):
        self._cancel()
        if self.tip is not None:
            try:
                self.tip.destroy()
            except tk.TclError:
                pass
            self.tip = None


class Row:
    def __init__(self, body, index, label_text, factory, label_width=27):
        self.frame = tk.Frame(body, bg=PANEL)
        self.frame.grid(row=index, column=0, sticky="ew", padx=2, pady=1)
        self.label = tk.Label(
            self.frame, text=label_text, bg=PANEL, fg=FG,
            anchor="w", width=label_width,
        )
        self.label.pack(side="left", padx=(8, 10))
        widget = factory(self.frame)
        widget.pack(side="left", fill="x", expand=True, padx=(0, 10), pady=2)
        self.widget = widget
        self.frame.grid_remove()

    def set_label(self, text):
        self.label.config(text=text)

    def show(self):
        self.frame.grid()

    def hide(self):
        self.frame.grid_remove()


class AddWeaponDialog(tk.Toplevel):
    def __init__(self, app: "App", entries: list[tuple[str, str]], patch_bases=()):
        super().__init__(app)
        self.app = app
        self.entries = entries
        self.patch_bases = {base.casefold() for base in patch_bases}
        self.result: tuple[str, str] | None = None
        self._items: list[tuple[str, str]] = []
        self._tips: list[Tooltip] = []

        self.title(app.t("add_title"))
        self.configure(bg=BG)
        self.geometry("680x600")
        self.transient(app)
        self.grab_set()

        top = tk.Frame(self, bg=BG)
        top.pack(fill="x", padx=14, pady=(14, 4))
        tk.Label(top, text=app.t("add_search"), bg=BG, fg=MUTED).pack(anchor="w")
        self.filter_var = tk.StringVar()
        entry = ttk.Entry(top, textvariable=self.filter_var)
        entry.pack(fill="x", pady=(4, 0))
        entry.focus_set()
        entry.bind("<KeyRelease>", lambda _e: self._refresh())
        entry.bind("<Return>", lambda _e: self._ok())
        self._tips.append(Tooltip(entry, lambda: app.t("tip_search")))

        filters = tk.Frame(self, bg=BG)
        filters.pack(fill="x", padx=14, pady=(8, 0))
        for column in range(3):
            filters.columnconfigure(column, weight=1)
        self.owner_combo = ttk.Combobox(
            filters, values=app.filter_values("owner"), state="readonly", width=14,
        )
        self.owner_combo.current(0)
        self.owner_combo.grid(row=0, column=0, sticky="ew", padx=(0, 6))
        self.cat_combo = ttk.Combobox(
            filters, values=app.filter_values("category"), state="readonly", width=14,
        )
        self.cat_combo.current(0)
        self.cat_combo.grid(row=0, column=1, sticky="ew", padx=(0, 6))
        self.sort_combo = ttk.Combobox(
            filters, values=app.filter_values("sort"), state="readonly", width=14,
        )
        self.sort_combo.current(0)
        self.sort_combo.grid(row=0, column=2, sticky="ew")
        for combo, tip_key in (
            (self.owner_combo, "tip_owner"),
            (self.cat_combo, "tip_cat"),
            (self.sort_combo, "tip_sort"),
        ):
            combo.bind("<<ComboboxSelected>>", lambda _e: self._refresh())
            self._tips.append(Tooltip(combo, lambda key=tip_key: app.t(key)))

        self.count_var = tk.StringVar()
        tk.Label(self, textvariable=self.count_var, bg=BG, fg=MUTED, anchor="w").pack(
            fill="x", padx=14, pady=(6, 0)
        )

        wrap = tk.Frame(self, bg=BG)
        wrap.pack(fill="both", expand=True, padx=14, pady=6)
        self.listbox = tk.Listbox(
            wrap, bg=PANE2, fg=FG, selectbackground=ACCENT, selectforeground=INK,
            activestyle="none", bd=0, highlightthickness=0, font=("Consolas", 9),
            exportselection=False,
        )
        sb = ttk.Scrollbar(wrap, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<Double-Button-1>", lambda _e: self._ok())

        btns = tk.Frame(self, bg=BG)
        btns.pack(fill="x", padx=14, pady=(0, 14))
        ttk.Button(btns, text=app.t("add_cancel"), command=self.destroy).pack(side="right")
        ttk.Button(
            btns, text=app.t("add_ok"), style="Accent.TButton", command=self._ok
        ).pack(side="right", padx=(0, 8))
        self._refresh()

    def _visible_entries(self) -> list[tuple[str, str]]:
        query = self.filter_var.get().strip().casefold()
        owner = OWNER_KEYS[max(self.owner_combo.current(), 0)]
        category = CATEGORY_KEYS[max(self.cat_combo.current(), 0)]
        sort_key = SORT_KEYS[max(self.sort_combo.current(), 0)]
        items = []
        for sid, kind in self.entries:
            base = base_sid(sid)
            entry_owner = "player" if kind == "gs" else sid_owner(sid)
            if query and query not in entry_search_blob(sid, base, self.app.lang):
                continue
            if owner != "all" and entry_owner != owner:
                continue
            if category != "all" and weapon_category(base, sid) != category:
                continue
            items.append((sid, kind))
        if sort_key == "modified":
            items.sort(key=lambda item: (
                base_sid(item[0]).casefold() not in self.patch_bases,
                friendly_name(base_sid(item[0]), self.app.lang).casefold(),
                item[0].casefold(),
            ))
        elif sort_key == "sid":
            items.sort(key=lambda item: item[0].casefold())
        else:
            items.sort(key=lambda item: (
                friendly_name(base_sid(item[0]), self.app.lang).casefold(),
                item[0].casefold(),
            ))
        return items

    def _refresh(self):
        self._items = self._visible_entries()
        shown = self._items[:600]
        self.listbox.delete(0, "end")
        for name, kind in shown:
            kind_label = self.app.t(
                "add_kind_player" if kind == "player" else "add_kind_gs"
            )
            friendly = friendly_name(base_sid(name), self.app.lang)
            self.listbox.insert("end", f"{friendly}   {name}  [{kind_label}]")
        extra = ""
        if len(self._items) > len(shown):
            extra = self.app.t("add_showing", shown=len(shown))
        self.count_var.set(self.app.t("add_count", count=len(self._items), extra=extra))

    def _ok(self):
        selection = self.listbox.curselection()
        if not selection:
            messagebox.showinfo(
                self.app.t("add_none_title"), self.app.t("add_none_msg"), parent=self
            )
            return
        self.result = self._items[selection[0]]
        self.destroy()


class App(tk.Tk):
    def __init__(self, lang_override: str | None = None):
        super().__init__()
        self.settings = read_settings()
        lang = self.settings.get("language", "en")
        if lang not in TRANSLATIONS:
            lang = "en"
        if lang_override in TRANSLATIONS:
            lang = lang_override
        self.lang = lang

        self.geometry("1280x820")
        self.minsize(1040, 680)
        self.configure(bg=BG)
        self.option_add("*TCombobox*Listbox.background", FIELD)
        self.option_add("*TCombobox*Listbox.foreground", FG)
        self.option_add("*TCombobox*Listbox.selectBackground", ACCENT)
        self.option_add("*TCombobox*Listbox.selectForeground", INK)

        self.player_doc: CfgDoc | None = None
        self.gs_doc: CfgDoc | None = None
        self.weapons: list[Weapon] = []
        self.current: Weapon | None = None
        self.dirty = False
        self._loading = False
        self._vanilla_cache: dict[str, CfgDoc] = {}
        self._status_key = "status_ready"
        self._status_kwargs: dict = {}
        self._tooltips: list[Tooltip] = []

        self._init_vars()
        self._init_style()
        self._build_ui()
        self.title(self.t("app_title"))
        self.reload_files(confirm=False)
        self.protocol("WM_DELETE_WINDOW", self._on_close)
        self.bind("<Control-s>", lambda _e: self.do_save(pack=True))
        self.bind("<Control-S>", lambda _e: self.do_save(pack=False))

    # -- i18n ----------------------------------------------------------
    def t(self, key: str, **kwargs) -> str:
        return translate(self.lang, key, **kwargs)

    def set_status(self, key: str, **kwargs):
        self._status_key = key
        self._status_kwargs = kwargs
        self.status_var.set(self.t(key, **kwargs))

    def _persist(self):
        write_settings({
            "mods_dir": self.mods_var.get().strip(),
            "language": self.lang,
        })

    # -- state ---------------------------------------------------------
    def _init_vars(self):
        self.v_player = {name: tk.StringVar() for name in PLAYER_FIELDS}
        self.v_pierce = tk.BooleanVar()
        self.v_maxammo = tk.StringVar()
        self.v_recoil = tk.StringVar()
        self.v_deftype = tk.StringVar()
        self.v_fire = {ftype: tk.BooleanVar() for ftype in FIRE_TYPES}
        self.v_caliber = tk.StringVar()
        self.v_proj = {ammo: (tk.BooleanVar(), tk.StringVar()) for ammo in AMMO_TYPES}
        self.mods_var = tk.StringVar(value=self.settings.get("mods_dir", ""))
        self.lang_name_var = tk.StringVar(value=LANG_NAMES[self.lang])
        self.search_var = tk.StringVar()
        self.status_var = tk.StringVar(value=self.t("status_ready"))
        self.visible: list[Weapon] = []

        tracked = (
            list(self.v_player.values())
            + [self.v_pierce, self.v_maxammo, self.v_recoil, self.v_deftype, self.v_caliber]
            + list(self.v_fire.values())
            + [pair[0] for pair in self.v_proj.values()]
            + [pair[1] for pair in self.v_proj.values()]
        )
        for var in tracked:
            var.trace_add("write", self._on_var_changed)

    def _on_var_changed(self, *_args):
        if not self._loading:
            self.dirty = True
            self.set_status("status_unsaved")

    def filter_values(self, kind: str) -> list[str]:
        if kind == "owner":
            return [self.t("flt_owner_" + key) for key in OWNER_KEYS]
        if kind == "category":
            return [self.t("flt_cat_" + key) for key in CATEGORY_KEYS]
        return [self.t("sort_" + key) for key in SORT_KEYS]

    def _filter_keys(self):
        return (
            self.search_var.get(),
            OWNER_KEYS[max(self.owner_combo.current(), 0)],
            CATEGORY_KEYS[max(self.cat_combo.current(), 0)],
            SORT_KEYS[max(self.sort_combo.current(), 0)],
        )

    def _on_filter_changed(self, *_args):
        self.refresh_view()

    def _reload_filter_combos(self):
        for combo, kind in (
            (self.owner_combo, "owner"),
            (self.cat_combo, "category"),
            (self.sort_combo, "sort"),
        ):
            index = max(combo.current(), 0)
            combo.configure(values=self.filter_values(kind))
            combo.current(index)

    def _on_lang_change(self, _event=None):
        code = LANGUAGE_CODES.get(self.lang_name_var.get(), "en")
        if code == self.lang:
            return
        self.lang = code
        self._persist()
        self.apply_language()

    def apply_language(self):
        self.commit_current()
        self.title(self.t("app_title"))
        self.sidebar_title.config(text=self.t("sidebar_title"))
        self.sidebar_sub.config(text=self.t("sidebar_subtitle"))
        self.weapons_hdr.config(text=self.t("weapons_header"))
        self.search_label.config(text=self.t("search_label"))
        self.add_btn.config(text=self.t("btn_add_vanilla"))
        self.reload_btn.config(text=self.t("btn_reload"))
        self.reset_btn.config(text=self.t("btn_reset"))
        self.lang_label.config(text=self.t("label_language"))

        self.group_player.config(text=self.t("group_player"))
        self.group_gs.config(text=self.t("group_gs"))
        self.group_notes.config(text=self.t("group_notes"))
        self.notes_lbl.config(text=self.t("notes_text"))
        self.player_no_block.config(text=self.t("no_player_block"))
        self.gs_no_block.config(text=self.t("no_gs_block"))

        for name, row in self.player_rows.items():
            row.set_label(self.t("field_" + name))
        self.pierce_row.set_label(self.t("always_pierce"))
        self.pierce_chk.config(text=self.t("enabled"))

        self.gs_rows["maxammo"].set_label(self.t("gs_maxammo"))
        self.gs_rows["recoil"].set_label(self.t("gs_recoil"))
        self.gs_rows["deftype"].set_label(self.t("gs_deftype"))
        self.gs_rows["firetypes"].set_label(self.t("gs_firetypes"))
        self.gs_rows["caliber"].set_label(self.t("gs_caliber"))
        self.proj_header_lbl.config(text=self.t("gs_proj_header"))
        for ftype, chk in self.fire_chks.items():
            chk.config(text=self.t("fire_" + ftype))
        for ammo, (chk, _entry) in self.proj_chks.items():
            chk.config(text=self.t("ammo_" + ammo))

        self.mods_label.config(text=self.t("mods_folder"))
        self.browse_btn.config(text=self.t("browse"))
        self.save_cfg_btn.config(text=self.t("save_cfg"))
        self.pack_btn.config(text=self.t("save_pack"))
        self.hint_lbl.config(text=self.t("shortcut_hint"))

        self._reload_filter_combos()
        self._fit_row_labels()
        self.refresh_view()
        if self.current is not None:
            self._update_header(self.current)
        else:
            self.title_lbl.config(text=self.t("select_weapon"))
            self.sub_lbl.config(text="")
        self.status_var.set(self.t(self._status_key, **self._status_kwargs))

    def refresh_view(self, select_base=None):
        if select_base is None and self.current is not None:
            select_base = self.current.base
        self.commit_current()
        query, owner, category, sort_key = self._filter_keys()
        self.visible = filter_weapons(
            self.weapons, self.lang, query, owner, category, sort_key
        )
        self.view_count_lbl.config(
            text=self.t("view_count", shown=len(self.visible), total=len(self.weapons))
        )
        self.listbox.delete(0, "end")
        for weapon in self.visible:
            self.listbox.insert("end", weapon_label(weapon, self.lang))
        if not self.visible:
            self.listbox.selection_clear(0, "end")
            if self.current is None:
                self._load_widgets(None)
            self._update_reset_state()
            return
        index = 0
        if select_base:
            for i, weapon in enumerate(self.visible):
                if weapon.base == select_base:
                    index = i
                    break
        self.listbox.selection_set(index)
        self.listbox.activate(index)
        self._select_index(index)
        self._update_reset_state()

    def _update_reset_state(self):
        self.reset_btn.state(["!disabled"] if self.current is not None else ["disabled"])

    def _fit_row_labels(self):
        groups = [
            list(self.player_rows.values()) + [self.pierce_row],
            list(self.gs_rows.values()),
        ]
        for rows in groups:
            texts = [row.label.cget("text") for row in rows]
            width = min(max([len(text) for text in texts] + [12]), 56)
            for row in rows:
                if row.label.cget("text"):
                    row.label.config(width=width)

    # -- styling -------------------------------------------------------
    def _init_style(self):
        style = ttk.Style(self)
        try:
            style.theme_use("clam")
        except tk.TclError:
            pass
        style.configure(".", background=BG, foreground=FG, font=("Segoe UI", 10))
        style.configure(
            "TEntry", fieldbackground=FIELD, foreground=FG, insertcolor=FG,
            bordercolor=BORDER, lightcolor=BORDER, darkcolor=BORDER, padding=4,
        )
        style.map(
            "TEntry",
            bordercolor=[("focus", ACCENT)],
            lightcolor=[("focus", ACCENT)],
            darkcolor=[("focus", ACCENT)],
        )
        style.configure(
            "TCombobox", fieldbackground=FIELD, background=PANE2, foreground=FG,
            arrowcolor=FG, bordercolor=BORDER, padding=3,
        )
        style.map(
            "TCombobox",
            fieldbackground=[("readonly", FIELD)],
            foreground=[("readonly", FG)],
            bordercolor=[("focus", ACCENT)],
            arrowcolor=[("disabled", MUTED)],
        )
        style.configure(
            "TButton", background=PANE2, foreground=FG, bordercolor=BORDER,
            focusthickness=0, padding=(12, 6),
        )
        style.map(
            "TButton",
            background=[("active", SEL), ("pressed", "#46525f")],
            foreground=[("disabled", MUTED)],
        )
        style.configure(
            "Accent.TButton", background=ACCENT, foreground=INK,
            bordercolor=ACCENT, focusthickness=0, padding=(14, 7),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Accent.TButton",
            background=[("active", "#e0bc63"), ("pressed", "#b8953f")],
            foreground=[("disabled", "#5a5340")],
        )
        style.configure(
            "Danger.TButton", background="#8e3333", foreground="#f7e9e9",
            bordercolor="#8e3333", focusthickness=0, padding=(12, 6),
            font=("Segoe UI", 10, "bold"),
        )
        style.map(
            "Danger.TButton",
            background=[
                ("disabled", "#3c2b2b"),
                ("active", "#a84040"),
                ("pressed", "#732828"),
            ],
            foreground=[("disabled", "#6b5555")],
            bordercolor=[("disabled", BORDER)],
        )
        style.configure(
            "TCheckbutton", background=PANEL, foreground=FG,
            focuscolor=PANEL, indicatorcolor=FIELD,
        )
        style.map(
            "TCheckbutton",
            background=[("active", PANEL)],
            foreground=[("disabled", MUTED)],
        )
        style.configure(
            "TLabelframe", background=PANEL, bordercolor=BORDER,
            lightcolor=BORDER, darkcolor=BORDER, relief="solid",
        )
        style.configure(
            "TLabelframe.Label", background=PANEL, foreground=ACCENT,
            font=("Segoe UI", 10, "bold"),
        )
        style.configure(
            "Vertical.TScrollbar", background=PANE2, troughcolor=BG,
            bordercolor=BG, arrowcolor=FG,
        )
        style.map("Vertical.TScrollbar", background=[("active", SEL)])

    # -- layout --------------------------------------------------------
    def _build_ui(self):
        self.columnconfigure(0, minsize=380)
        self.columnconfigure(1, weight=1)
        self.rowconfigure(0, weight=1)

        side = tk.Frame(self, bg=PANEL)
        side.grid(row=0, column=0, sticky="nsew")
        side.pack_propagate(False)

        self.sidebar_title = tk.Label(
            side, text=self.t("sidebar_title"), bg=PANEL, fg=ACCENT,
            font=("Segoe UI", 16, "bold"), anchor="w",
        )
        self.sidebar_title.pack(fill="x", padx=18, pady=(18, 0))
        self.sidebar_sub = tk.Label(
            side, text=self.t("sidebar_subtitle"), bg=PANEL, fg=MUTED,
            font=("Consolas", 9), anchor="w",
        )
        self.sidebar_sub.pack(fill="x", padx=18, pady=(2, 12))

        tk.Frame(side, bg=BORDER, height=1).pack(fill="x", padx=18)
        self.weapons_hdr = tk.Label(
            side, text=self.t("weapons_header"), bg=PANEL, fg=MUTED,
            font=("Segoe UI", 9, "bold"), anchor="w",
        )
        self.weapons_hdr.pack(fill="x", padx=18, pady=(14, 4))

        filters = tk.Frame(side, bg=PANEL)
        filters.pack(fill="x", padx=14, pady=(0, 6))
        filters.columnconfigure(0, weight=1)
        filters.columnconfigure(1, weight=1)
        self.search_label = tk.Label(
            filters, text=self.t("search_label"), bg=PANEL, fg=MUTED,
            font=("Segoe UI", 9), anchor="w",
        )
        self.search_label.grid(row=0, column=0, sticky="w", padx=(4, 0))
        self.search_entry = ttk.Entry(filters, textvariable=self.search_var)
        self.search_entry.grid(row=1, column=0, columnspan=2, sticky="ew", pady=(2, 0))
        self.owner_combo = ttk.Combobox(
            filters, values=self.filter_values("owner"), state="readonly", width=14,
        )
        self.owner_combo.current(0)
        self.owner_combo.grid(row=2, column=0, sticky="ew", padx=(0, 3), pady=(5, 0))
        self.sort_combo = ttk.Combobox(
            filters, values=self.filter_values("sort"), state="readonly", width=14,
        )
        self.sort_combo.current(0)
        self.sort_combo.grid(row=2, column=1, sticky="ew", padx=(3, 0), pady=(5, 0))
        self.cat_combo = ttk.Combobox(
            filters, values=self.filter_values("category"), state="readonly", width=20,
        )
        self.cat_combo.current(0)
        self.cat_combo.grid(row=3, column=0, columnspan=2, sticky="ew", pady=(5, 0))
        self.view_count_lbl = tk.Label(
            filters, text="", bg=PANEL, fg=MUTED, font=("Segoe UI", 8), anchor="w",
        )
        self.view_count_lbl.grid(row=4, column=0, columnspan=2, sticky="w", padx=(4, 0))
        self.search_var.trace_add("write", self._on_filter_changed)
        self.owner_combo.bind("<<ComboboxSelected>>", self._on_filter_changed)
        self.sort_combo.bind("<<ComboboxSelected>>", self._on_filter_changed)
        self.cat_combo.bind("<<ComboboxSelected>>", self._on_filter_changed)

        list_wrap = tk.Frame(side, bg=PANEL)
        list_wrap.pack(fill="both", expand=True, padx=14, pady=(0, 10))
        self.listbox = tk.Listbox(
            list_wrap, bg=PANE2, fg=FG, selectbackground=ACCENT, selectforeground=INK,
            activestyle="none", bd=0, highlightthickness=0,
            font=("Segoe UI", 9), exportselection=False,
        )
        sb = ttk.Scrollbar(list_wrap, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=sb.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        sb.pack(side="right", fill="y")
        self.listbox.bind("<<ListboxSelect>>", self._on_list_select)

        side_btns = tk.Frame(side, bg=PANEL)
        side_btns.pack(fill="x", padx=14, pady=(0, 16))
        self.reset_btn = ttk.Button(
            side_btns, text=self.t("btn_reset"), style="Danger.TButton",
            command=self.reset_current_to_vanilla,
        )
        self.reset_btn.pack(fill="x", pady=(0, 6))
        self.reset_btn.state(["disabled"])
        self.add_btn = ttk.Button(
            side_btns, text=self.t("btn_add_vanilla"), command=self.open_add_dialog
        )
        self.add_btn.pack(fill="x", pady=(0, 6))
        self.reload_btn = ttk.Button(
            side_btns, text=self.t("btn_reload"), command=self.reload_files
        )
        self.reload_btn.pack(fill="x")

        main = tk.Frame(self, bg=BG)
        main.grid(row=0, column=1, sticky="nsew")

        settings_bar = tk.Frame(main, bg=BG)
        settings_bar.pack(fill="x", padx=20, pady=(10, 0))
        self.lang_label = tk.Label(
            settings_bar, text=self.t("label_language"), bg=BG, fg=MUTED,
            font=("Segoe UI", 9),
        )
        self.lang_label.pack(side="left")
        self.lang_combo = ttk.Combobox(
            settings_bar, textvariable=self.lang_name_var,
            values=[LANG_NAMES["en"], LANG_NAMES["uk"]],
            state="readonly", width=14,
        )
        self.lang_combo.pack(side="left", padx=(8, 0))
        self.lang_combo.bind("<<ComboboxSelected>>", self._on_lang_change)

        head = tk.Frame(main, bg=BG)
        head.pack(fill="x", padx=20, pady=(8, 4))
        self.title_lbl = tk.Label(
            head, text=self.t("select_weapon"), bg=BG, fg=FG,
            font=("Segoe UI", 17, "bold"), anchor="w",
        )
        self.title_lbl.pack(fill="x")
        self.sub_lbl = tk.Label(
            head, text="", bg=BG, fg=MUTED, font=("Consolas", 9), anchor="w",
        )
        self.sub_lbl.pack(fill="x", pady=(2, 0))

        status = tk.Label(
            main, textvariable=self.status_var, bg=BG, fg=MUTED,
            font=("Segoe UI", 9), anchor="w",
        )
        status.pack(side="bottom", fill="x", padx=20, pady=(2, 8))

        bar = tk.Frame(main, bg=PANEL)
        bar.pack(side="bottom", fill="x")

        mods_row = tk.Frame(bar, bg=PANEL)
        mods_row.pack(fill="x", padx=14, pady=(10, 0))
        self.mods_label = tk.Label(
            mods_row, text=self.t("mods_folder"), bg=PANEL, fg=MUTED,
            font=("Segoe UI", 9),
        )
        self.mods_label.pack(side="left", padx=(0, 8))
        self.mods_entry = ttk.Entry(mods_row, textvariable=self.mods_var)
        self.mods_entry.pack(side="left", fill="x", expand=True)
        self.browse_btn = ttk.Button(
            mods_row, text=self.t("browse"), command=self._browse_mods
        )
        self.browse_btn.pack(side="left", padx=(8, 0))

        actions = tk.Frame(bar, bg=PANEL)
        actions.pack(fill="x", padx=14, pady=(8, 12))
        self.save_cfg_btn = ttk.Button(
            actions, text=self.t("save_cfg"), command=lambda: self.do_save(pack=False)
        )
        self.save_cfg_btn.pack(side="left")
        self.pack_btn = ttk.Button(
            actions, text=self.t("save_pack"), style="Accent.TButton",
            command=lambda: self.do_save(pack=True),
        )
        self.pack_btn.pack(side="right")
        self.hint_lbl = tk.Label(
            actions, text=self.t("shortcut_hint"), bg=PANEL, fg=MUTED,
            font=("Segoe UI", 9),
        )
        self.hint_lbl.pack(side="right", padx=12)

        scroll = tk.Frame(main, bg=BG)
        scroll.pack(fill="both", expand=True, padx=10, pady=6)
        canvas = tk.Canvas(scroll, bg=BG, highlightthickness=0, bd=0)
        self._scroll_canvas = canvas
        vsb = ttk.Scrollbar(scroll, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")
        inner = tk.Frame(canvas, bg=BG)
        window = canvas.create_window((0, 0), window=inner, anchor="nw")
        inner.bind(
            "<Configure>",
            lambda _e: canvas.configure(scrollregion=canvas.bbox("all")),
        )
        canvas.bind(
            "<Configure>", lambda e: canvas.itemconfigure(window, width=e.width)
        )
        canvas.bind("<Enter>", lambda _e: canvas.bind_all("<MouseWheel>", self._wheel))
        canvas.bind("<Leave>", lambda _e: canvas.unbind_all("<MouseWheel>"))

        self._build_player_group(inner)
        self._build_gs_group(inner)
        self._build_add_group(inner)
        self._fit_row_labels()

        self._tooltips.append(Tooltip(self.add_btn, lambda: self.t("tip_add")))
        self._tooltips.append(Tooltip(self.reload_btn, lambda: self.t("tip_reload")))
        self._tooltips.append(Tooltip(self.reset_btn, lambda: self.t("tip_reset")))
        self._tooltips.append(Tooltip(self.pack_btn, lambda: self.t("tip_pack")))
        self._tooltips.append(Tooltip(self.lang_combo, lambda: self.t("tip_lang")))
        self._tooltips.append(Tooltip(self.mods_entry, lambda: self.t("tip_mods")))
        self._tooltips.append(Tooltip(self.browse_btn, lambda: self.t("tip_mods")))
        self._tooltips.append(Tooltip(self.search_entry, lambda: self.t("tip_search")))
        self._tooltips.append(Tooltip(self.owner_combo, lambda: self.t("tip_owner")))
        self._tooltips.append(Tooltip(self.cat_combo, lambda: self.t("tip_cat")))
        self._tooltips.append(Tooltip(self.sort_combo, lambda: self.t("tip_sort")))

    def _wheel(self, event):
        delta = -1 if event.delta > 0 else 1
        self._scroll_canvas.yview_scroll(delta * 2, "units")

    def _make_group(self, parent, title):
        frame = ttk.LabelFrame(parent, text=title, style="TLabelframe")
        frame.pack(fill="x", padx=16, pady=(12, 4))
        body = tk.Frame(frame, bg=PANEL)
        body.pack(fill="x", padx=6, pady=6)
        body.columnconfigure(0, weight=1)
        return frame, body

    def _build_player_group(self, parent):
        self.group_player, body = self._make_group(parent, self.t("group_player"))
        self.player_rows: dict[str, Row] = {}
        self.player_no_block = tk.Label(
            body, text=self.t("no_player_block"), bg=PANEL, fg=MUTED, anchor="w",
        )
        self.player_no_block.grid(row=0, column=0, sticky="ew", padx=10, pady=6)
        row = 0
        for name in PLAYER_FIELDS:
            row += 1
            self.player_rows[name] = Row(
                body, row, self.t("field_" + name),
                lambda parent, name=name: ttk.Entry(  # noqa: E731
                    parent, textvariable=self.v_player[name], width=18
                ),
            )
        row += 1

        def pierce_factory(parent):
            self.pierce_chk = ttk.Checkbutton(
                parent, text=self.t("enabled"), variable=self.v_pierce
            )
            return self.pierce_chk

        self.pierce_row = Row(
            body, row, self.t("always_pierce"), pierce_factory
        )

    def _build_gs_group(self, parent):
        self.group_gs, body = self._make_group(parent, self.t("group_gs"))
        self.gs_rows: dict[str, Row] = {}
        self.gs_no_block = tk.Label(
            body, text=self.t("no_gs_block"), bg=PANEL, fg=MUTED, anchor="w",
        )
        self.gs_no_block.grid(row=0, column=0, sticky="ew", padx=10, pady=6)
        row = 0

        def entry_factory(var):
            return lambda parent: ttk.Entry(parent, textvariable=var, width=18)

        row += 1
        self.gs_rows["maxammo"] = Row(
            body, row, self.t("gs_maxammo"), entry_factory(self.v_maxammo)
        )
        row += 1
        self.gs_rows["recoil"] = Row(
            body, row, self.t("gs_recoil"), entry_factory(self.v_recoil)
        )
        row += 1
        self.gs_rows["deftype"] = Row(
            body, row, self.t("gs_deftype"),
            lambda parent: ttk.Combobox(
                parent, textvariable=self.v_deftype, values=DEFAULT_FIRE_TYPES, width=26
            ),
        )
        row += 1

        self.fire_chks: dict[str, ttk.Checkbutton] = {}

        def fire_factory(parent):
            box = tk.Frame(parent, bg=PANEL)
            for ftype in FIRE_TYPES:
                chk = ttk.Checkbutton(
                    box, text=self.t("fire_" + ftype), variable=self.v_fire[ftype]
                )
                chk.pack(side="left", padx=(0, 10))
                self.fire_chks[ftype] = chk
            return box

        self.gs_rows["firetypes"] = Row(
            body, row, self.t("gs_firetypes"), fire_factory
        )
        row += 1
        self.gs_rows["caliber"] = Row(
            body, row, self.t("gs_caliber"),
            lambda parent: ttk.Combobox(
                parent, textvariable=self.v_caliber, values=CALIBERS, width=30
            ),
        )
        row += 1

        self.proj_header_lbl = tk.Label(
            body, text=self.t("gs_proj_header"), bg=PANEL, fg=MUTED,
            font=("Segoe UI", 9), anchor="w",
        )
        self.proj_header_lbl.grid(row=row, column=0, sticky="ew", padx=12, pady=(8, 0))
        self.proj_header_lbl.grid_remove()
        self.proj_rows: dict[str, Row] = {}
        self.proj_chks: dict[str, tuple] = {}

        def proj_factory(ammo):
            def build(parent):
                box = tk.Frame(parent, bg=PANEL)
                chk = ttk.Checkbutton(
                    box, text=self.t("ammo_" + ammo), variable=self.v_proj[ammo][0]
                )
                chk.pack(side="left")
                entry = ttk.Entry(box, textvariable=self.v_proj[ammo][1], width=18)
                entry.pack(side="left", padx=(10, 0), fill="x", expand=True)
                self.proj_chks[ammo] = (chk, entry)
                return box
            return build

        for ammo in AMMO_TYPES:
            row += 1
            self.proj_rows[ammo] = Row(
                body, row, "", proj_factory(ammo), label_width=2
            )

    def _build_add_group(self, parent):
        self.group_notes, body = self._make_group(parent, self.t("group_notes"))
        self.notes_lbl = tk.Label(
            body, text=self.t("notes_text"), bg=PANEL, fg=MUTED,
            justify="left", font=("Segoe UI", 9), anchor="w", wraplength=780,
        )
        self.notes_lbl.grid(row=0, column=0, sticky="w", padx=10, pady=6)

    # -- data loading ---------------------------------------------------
    def reload_files(self, select_base=None, confirm=True):
        if confirm and self.dirty:
            if not messagebox.askyesno(
                self.t("dlg_reload_title"), self.t("dlg_reload_msg")
            ):
                return
        keep = select_base
        if keep is None and self.current is not None:
            keep = self.current.base
        try:
            self.player_doc = CfgDoc(PLAYER_CFG)
            self.gs_doc = CfgDoc(GS_CFG)
        except Exception as exc:
            self.player_doc = None
            self.gs_doc = None
            self.weapons = []
            self.visible = []
            self.current = None
            self.listbox.delete(0, "end")
            self._load_widgets(None)
            self._update_reset_state()
            self.set_status("status_load_failed")
            messagebox.showerror(
                self.t("dlg_load_failed_title"),
                self.t(
                    "dlg_load_failed_msg",
                    error=exc,
                    files="\n".join([PLAYER_CFG, GS_CFG]),
                ),
            )
            return
        self.weapons = build_weapons(
            self.player_doc, self.gs_doc, self._vanilla_player_doc()
        )
        self.current = None
        self.refresh_view(keep)
        self.dirty = False
        self.set_status("status_loaded", count=len(self.weapons))

    def _on_list_select(self, _event=None):
        selection = self.listbox.curselection()
        if selection:
            self._select_index(selection[0])

    def _select_index(self, index):
        if not (0 <= index < len(self.visible)):
            return
        weapon = self.visible[index]
        if weapon is self.current:
            return
        self.commit_current()
        self.current = weapon
        self._load_widgets(weapon)
        self._update_header(weapon)
        self._update_reset_state()

    def _update_header(self, weapon):
        self.title_lbl.config(text=friendly_name(weapon.base, self.lang))
        parts = []
        if weapon.player is not None:
            parts.append(self.t("sid_player") + ": " + weapon.player.name)
        if weapon.gs is not None:
            parts.append(self.t("sid_gs") + ": " + weapon.gs.name)
        if weapon.player is not None and not weapon.player_is_patch:
            parts.append(self.t("sid_vanilla"))
        self.sub_lbl.config(text="   |   ".join(parts))

    def _load_widgets(self, weapon):
        self._loading = True
        try:
            if weapon is None:
                self.title_lbl.config(text=self.t("select_weapon"))
                self.sub_lbl.config(text="")
                for row in self.player_rows.values():
                    row.hide()
                self.pierce_row.hide()
                self.player_no_block.grid()
                for row in self.gs_rows.values():
                    row.hide()
                for row in self.proj_rows.values():
                    row.hide()
                self.proj_header_lbl.grid_remove()
                self.gs_no_block.grid()
                return

            # player block
            if weapon.player is None:
                self.player_no_block.grid()
            else:
                self.player_no_block.grid_remove()
            for name, row in self.player_rows.items():
                if name in weapon.player_values:
                    self.v_player[name].set(weapon.player_values[name])
                    row.show()
                else:
                    row.hide()
            if weapon.player_bool is not None:
                self.v_pierce.set(bool(weapon.player_bool))
                self.pierce_row.show()
            else:
                self.pierce_row.hide()
            # general setup block
            if weapon.gs is None:
                self.gs_no_block.grid()
                for row in self.gs_rows.values():
                    row.hide()
                for row in self.proj_rows.values():
                    row.hide()
                self.proj_header_lbl.grid_remove()
                return
            self.gs_no_block.grid_remove()

            if "MaxAmmo" in weapon.gs_values:
                self.v_maxammo.set(weapon.gs_values["MaxAmmo"])
                self.gs_rows["maxammo"].show()
            else:
                self.gs_rows["maxammo"].hide()

            if weapon.recoil_radius is not None:
                self.v_recoil.set(weapon.recoil_radius)
                self.gs_rows["recoil"].show()
            else:
                self.gs_rows["recoil"].hide()

            if "DefaultFireType" in weapon.gs_values:
                self.v_deftype.set(weapon.gs_values["DefaultFireType"])
                self.gs_rows["deftype"].show()
            else:
                self.gs_rows["deftype"].hide()

            if weapon.has_fire_types:
                for ftype, var in self.v_fire.items():
                    var.set(ftype in weapon.fire_types)
                self.gs_rows["firetypes"].show()
            else:
                self.gs_rows["firetypes"].hide()

            if weapon.caliber is not None:
                self.v_caliber.set(weapon.caliber)
                self.gs_rows["caliber"].show()
            else:
                self.gs_rows["caliber"].hide()

            if weapon.has_projectiles:
                self.proj_header_lbl.grid()
                mapping = {ammo: proj for ammo, proj in weapon.projectiles}
                for ammo, row in self.proj_rows.items():
                    if ammo in mapping:
                        self.v_proj[ammo][0].set(True)
                        self.v_proj[ammo][1].set(mapping[ammo])
                    else:
                        self.v_proj[ammo][0].set(False)
                        self.v_proj[ammo][1].set("")
                    row.show()
            else:
                self.proj_header_lbl.grid_remove()
                for row in self.proj_rows.values():
                    row.hide()
        finally:
            self._loading = False

    def commit_current(self):
        weapon = self.current
        if weapon is None or self._loading:
            return
        for name in PLAYER_FIELDS:
            if name in weapon.player_values:
                weapon.player_values[name] = self.v_player[name].get()
        if weapon.player_bool is not None:
            weapon.player_bool = self.v_pierce.get()
        if weapon.gs is not None:
            if "MaxAmmo" in weapon.gs_values:
                weapon.gs_values["MaxAmmo"] = self.v_maxammo.get()
            if "DefaultFireType" in weapon.gs_values:
                weapon.gs_values["DefaultFireType"] = self.v_deftype.get()
            if weapon.recoil_radius is not None:
                weapon.recoil_radius = self.v_recoil.get()
            if weapon.has_fire_types:
                weapon.fire_types = [ftype for ftype in FIRE_TYPES if self.v_fire[ftype].get()]
            if weapon.caliber is not None:
                weapon.caliber = self.v_caliber.get()
            if weapon.has_projectiles:
                weapon.projectiles = [
                    [ammo, self.v_proj[ammo][1].get()]
                    for ammo in AMMO_TYPES
                    if self.v_proj[ammo][0].get()
                ]

    # -- save / pack ----------------------------------------------------
    def do_save(self, pack=False):
        if self.current is not None:
            self.commit_current()
        errors = validate_and_normalize(self.weapons, tr=self.t)
        if errors:
            messagebox.showerror(
                self.t("dlg_invalid_title"),
                self.t("dlg_invalid_msg", errors="\n".join(errors[:15])),
            )
            return
        try:
            apply_model_to_docs(self.weapons, self.player_doc, self.gs_doc)
            self.player_doc.save()
            self.gs_doc.save()
        except Exception as exc:
            messagebox.showerror(self.t("dlg_save_failed"), str(exc))
            return

        keep_base = self.current.base if self.current else None
        self.dirty = False
        self.current = None
        self.reload_files(select_base=keep_base, confirm=False)
        self.dirty = False

        if pack:
            self.pack_and_deploy()
        else:
            messagebox.showinfo(
                self.t("dlg_saved_title"),
                self.t("dlg_saved_msg", player=PLAYER_CFG, gs=GS_CFG),
            )

    def reset_current_to_vanilla(self):
        weapon = self.current
        if weapon is None:
            return
        name = friendly_name(weapon.base, self.lang)
        sids = [sec.name for sec in (weapon.player, weapon.gs) if sec is not None]
        if not sids:
            return
        if not messagebox.askyesno(
            self.t("dlg_reset_title"),
            self.t("dlg_reset_msg", name=name, sid=", ".join(sids)),
        ):
            return
        self.commit_current()
        others = [item for item in self.weapons if item is not weapon]
        errors = validate_and_normalize(others, tr=self.t)
        if errors:
            messagebox.showerror(
                self.t("dlg_invalid_title"),
                self.t("dlg_invalid_first", errors="\n".join(errors[:15])),
            )
            return
        if self.player_doc is None or self.gs_doc is None:
            return
        try:
            apply_model_to_docs(others, self.player_doc, self.gs_doc)
            if weapon.player is not None:
                remove_section(self.player_doc, weapon.player.name)
            if weapon.gs is not None:
                remove_section(self.gs_doc, weapon.gs.name)
            self.player_doc.save()
            self.gs_doc.save()
        except Exception as exc:
            messagebox.showerror(self.t("dlg_save_failed"), str(exc))
            return

        try:
            index = self.visible.index(weapon)
        except ValueError:
            index = 0
        remaining = [item for item in self.visible if item is not weapon]
        next_base = remaining[min(index, len(remaining) - 1)].base if remaining else None
        self.dirty = False
        self.current = None
        self.reload_files(select_base=next_base, confirm=False)
        self.dirty = False
        self.set_status("status_reset", name=name, sid=", ".join(sids))

    def pack_and_deploy(self):
        repak = find_repak()
        if not repak:
            messagebox.showwarning(
                self.t("dlg_repak_missing_title"), self.t("dlg_repak_missing_msg")
            )
            return

        source_tree = os.path.join(UPDATED_DIR, "Stalker2")
        if not os.path.isdir(source_tree):
            messagebox.showerror(
                self.t("dlg_pack_failed_title"),
                self.t("pack_missing_folder", path=source_tree),
            )
            return

        staging = None
        try:
            staging = tempfile.mkdtemp(prefix="stalker2_pak_")
            shutil.copytree(
                source_tree,
                os.path.join(staging, "Stalker2"),
                ignore=shutil.ignore_patterns("*.pak", "*.exe", "*.utoc", "*.ucas"),
            )
            expected = {
                os.path.relpath(PLAYER_CFG, UPDATED_DIR).replace(os.sep, "/"),
                os.path.relpath(GS_CFG, UPDATED_DIR).replace(os.sep, "/"),
            }
            # Shared virtual paths: an empty override would replace other mods'
            # definitions of the same prototype file.
            for cfg_path in (PLAYER_CFG, GS_CFG):
                entry = os.path.relpath(cfg_path, UPDATED_DIR).replace(os.sep, "/")
                staged = os.path.join(staging, *entry.split("/"))
                if not os.path.exists(staged):
                    continue
                try:
                    empty = not CfgDoc(staged).sections()
                except Exception:
                    empty = False
                if empty:
                    os.remove(staged)
                    expected.discard(entry)
            for name in (PAK_NAME, *LEGACY_PAK_NAMES):
                old_pak = os.path.join(ROOT, name)
                if os.path.exists(old_pak):
                    os.remove(old_pak)
            proc = _run_hidden([repak, "pack", staging, PAK_PATH])
            if proc.returncode != 0:
                raise EditorError(
                    "repak failed:\n" + (proc.stderr or proc.stdout or "no output")
                )
            check = _run_hidden([repak, "list", PAK_PATH])
            entries = [line.strip() for line in check.stdout.splitlines() if line.strip()]
            cfgs = [entry for entry in entries if ".cfg" in entry.lower()]
            if not cfgs:
                raise EditorError("Packed archive contains no .cfg files.")
            packed = {entry.replace("\\", "/").strip().lstrip("/") for entry in entries}
            missing = expected - packed
            if missing:
                raise EditorError(
                    "Packed archive is missing patch files:\n" + "\n".join(sorted(missing))
                )
            if any("repak" in entry.lower() for entry in entries):
                raise EditorError("repak.exe leaked into the archive.")
            built_hash = sha256_file(PAK_PATH)
        except Exception as exc:
            messagebox.showerror(
                self.t("dlg_pack_failed_title"),
                self.t("dlg_pack_failed_msg", error=exc),
            )
            return
        finally:
            if staging:
                shutil.rmtree(staging, ignore_errors=True)

        deployed = ""
        mods_dir = self.mods_var.get().strip()
        warning = ""
        verified = False
        disabled: list[str] = []
        other_mods: list[str] = []
        if mods_dir:
            target = os.path.join(mods_dir, PAK_NAME)
            try:
                os.makedirs(mods_dir, exist_ok=True)
                shutil.copy2(PAK_PATH, target)
                if sha256_file(target) != built_hash:
                    raise OSError("copied pak does not match the freshly built one")
                verified = True
                deployed = target
                for name in LEGACY_PAK_NAMES:
                    old_pak = os.path.join(mods_dir, name)
                    if os.path.exists(old_pak):
                        os.remove(old_pak)
            except OSError as exc:
                warning = self.t("pack_copy_error", error=exc)
            # The game mounts every pak under Content/Paks (~mods subfolders
            # included); a second copy of the same file makes the winner depend
            # on load order, which is what made changes apply inconsistently.
            paks_root = game_paks_root(mods_dir)
            if paks_root:
                same_name, other_mods = find_shadowing_paks(
                    repak, paks_root, PAK_ENTRY, {PAK_PATH, target}
                )
                for path in same_name:
                    try:
                        disabled.append(disable_pak(path))
                    except OSError as exc:
                        warning += "\n" + str(exc)
            self._persist()

        summary = [
            self.t("pack_ok"),
            "",
            self.t("pack_archive", path=PAK_PATH),
            self.t("pack_entries", total=len(entries), cfgs=len(cfgs)),
        ]
        if deployed:
            summary.append(self.t("pack_deployed", path=deployed))
        if verified:
            summary.append(self.t("pack_verified", hash=built_hash[:12]))
        for path in disabled:
            summary.append(self.t("pack_shadow_disabled", path=path))
        for path in other_mods:
            summary.append(self.t("pack_shadow_other", path=path))
        summary.append("")
        summary.append(self.t("pack_command", name=PAK_NAME))
        messagebox.showinfo(
            self.t("dlg_pack_ok_title"), "\n".join(summary) + warning
        )

    def _browse_mods(self):
        folder = filedialog.askdirectory(title=self.t("browse_title"))
        if not folder:
            return
        folder = os.path.normpath(folder)
        if os.path.basename(folder).lower() == "paks":
            folder = os.path.join(folder, "~mods")
        self.mods_var.set(folder)
        self._persist()

    # -- add from vanilla ----------------------------------------------
    def _vanilla_player_doc(self) -> CfgDoc | None:
        if not os.path.exists(VANILLA_CHAR):
            return None
        if "player" not in self._vanilla_cache:
            try:
                self._vanilla_cache["player"] = CfgDoc(VANILLA_CHAR)
            except OSError:
                return None
        return self._vanilla_cache["player"]

    def _vanilla_docs(self) -> dict[str, CfgDoc] | None:
        missing = [p for p in (VANILLA_CHAR, VANILLA_GS) if not os.path.exists(p)]
        if missing:
            messagebox.showerror(
                self.t("dlg_vanilla_missing_title"),
                self.t("dlg_vanilla_missing_msg", missing="\n".join(missing)),
            )
            return None
        if "player" not in self._vanilla_cache:
            self._vanilla_cache["player"] = CfgDoc(VANILLA_CHAR)
        if "gs" not in self._vanilla_cache:
            self._vanilla_cache["gs"] = CfgDoc(VANILLA_GS)
        return self._vanilla_cache

    def open_add_dialog(self):
        docs = self._vanilla_docs()
        if docs is None:
            return
        bases = {weapon.base for weapon in self.weapons}
        entries = [
            (sec.name, "gs")
            for sec in docs["gs"].sections()
            if base_sid(sec.name) in bases
        ]
        entries.sort(key=lambda item: item[0].lower())
        dialog = AddWeaponDialog(
            self, entries,
            patch_bases=[w.base for w in self.weapons if w.gs is not None],
        )
        self.wait_window(dialog)
        if dialog.result:
            self.add_weapon_from_vanilla(*dialog.result)

    def add_weapon_from_vanilla(self, sid: str, kind: str):
        base = base_sid(sid)
        target = next((weapon for weapon in self.weapons if weapon.base == base), None)
        if target is None:
            messagebox.showerror(
                self.t("dlg_notfound_title"),
                self.t("dlg_notfound_msg", sid=sid, path=VANILLA_GS),
            )
            return
        if target.gs is not None:
            messagebox.showinfo(
                self.t("dlg_already_title"),
                self.t("dlg_already_msg", sid=sid, base=base),
            )
            return
        docs = self._vanilla_docs()
        if docs is None:
            return

        self.commit_current()
        errors = validate_and_normalize(self.weapons, tr=self.t)
        if errors:
            messagebox.showerror(
                self.t("dlg_invalid_title"),
                self.t("dlg_invalid_first", errors="\n".join(errors[:15])),
            )
            return
        try:
            apply_model_to_docs(self.weapons, self.player_doc, self.gs_doc)
        except Exception as exc:
            messagebox.showerror(self.t("dlg_update_failed"), str(exc))
            return

        vanilla_doc = docs["gs"]
        section = next(
            (sec for sec in vanilla_doc.sections() if sec.name == sid), None
        )
        if section is None:
            messagebox.showerror(
                self.t("dlg_notfound_title"),
                self.t("dlg_notfound_msg", sid=sid, path=vanilla_doc.path),
            )
            return
        append_block(self.gs_doc, build_gs_block(vanilla_doc, section))

        self.weapons = build_weapons(
            self.player_doc, self.gs_doc, self._vanilla_player_doc()
        )
        added = next(
            (item for item in self.weapons if item.base == base_sid(sid)), None
        )
        if added is not None:
            added.loaded_sig = None
        self.current = None
        self.search_var.set("")
        self.owner_combo.current(0)
        self.cat_combo.current(0)
        self.sort_combo.current(0)
        self.refresh_view(base_sid(sid))
        self.dirty = True
        self.set_status("status_added", sid=sid)

    # -- misc ------------------------------------------------------------
    def _on_close(self):
        if self.dirty and not messagebox.askyesno(
            self.t("dlg_quit_title"), self.t("dlg_quit_msg")
        ):
            return
        self._persist()
        self.destroy()


# ---------------------------------------------------------------------------
# Self-test (no GUI interaction needed)
# ---------------------------------------------------------------------------
def run_selftest() -> int:
    print("GUR - Gunsmith Utility & Reconfigurator self-test")
    ok = True

    en_keys = set(TRANSLATIONS["en"])
    uk_keys = set(TRANSLATIONS["uk"])
    missing = en_keys.symmetric_difference(uk_keys)
    print("  translations parity:", "OK" if not missing else f"FAIL {sorted(missing)}")
    ok = ok and not missing
    sample = TRANSLATIONS["uk"]["field_ArmorPiercing"]
    print("  uk label encoding:", "OK" if "Пробиття" in sample else "FAIL", "->", sample)
    ok = ok and "Пробиття" in sample

    for label, path in (("player", PLAYER_CFG), ("gs", GS_CFG)):
        if not os.path.exists(path):
            print("  MISSING:", path)
            return 1
        doc = CfgDoc(path)
        secs = doc.sections()
        print(f"  {label}: {len(secs)} sections -> " + ", ".join(s.name for s in secs))
        fd, tmp = tempfile.mkstemp(suffix=".cfg")
        os.close(fd)
        try:
            doc.save(tmp)
            with open(path, "rb") as fh:
                original = fh.read()
            with open(tmp, "rb") as fh:
                roundtrip = fh.read()
            same = original == roundtrip
            print(f"  {label}: save roundtrip byte-identical:", "OK" if same else "FAIL")
            ok = ok and same
        finally:
            if os.path.exists(tmp):
                os.unlink(tmp)

    vanilla_doc = CfgDoc(VANILLA_CHAR) if os.path.exists(VANILLA_CHAR) else None
    player_doc = CfgDoc(PLAYER_CFG)
    gs_doc = CfgDoc(GS_CFG)
    weapons = build_weapons(player_doc, gs_doc, vanilla_doc)
    for weapon in weapons:
        bits = []
        if weapon.player is not None:
            bits.append(f"player:{len(weapon.player_values)} fields")
        if weapon.gs is not None:
            bits.append(
                f"gs:ammo={weapon.gs_values.get('MaxAmmo')},recoil={weapon.recoil_radius},"
                f"ft={weapon.fire_types},proj={weapon.projectiles}"
            )
        print("  weapon EN:", weapon_label(weapon, "en"))
        print("  weapon UK:", weapon_label(weapon, "uk"), "|", ", ".join(bits) or "empty")
    bases = {weapon.base for weapon in weapons}
    print("  weapons parsed:", len(weapons), "->", ", ".join(sorted(bases)) or "none")
    expected_bases = {base_sid(sec.name) for sec in player_doc.sections()}
    if vanilla_doc is not None:
        expected_bases |= {
            base_sid(sec.name) for sec in vanilla_doc.sections()
            if sid_owner(sec.name) == "player"
        }
    count_ok = bool(weapons) and len(weapons) == len(expected_bases)
    print(
        "  all player weapons listed:",
        "OK" if count_ok else f"FAIL ({len(weapons)} vs {len(expected_bases)})",
    )
    ok = ok and count_ok
    ui_free = all(not (set(AUTO_UI_FIELDS) & set(w.player_values)) for w in weapons)
    print("  no UI rows in the model:", "OK" if ui_free else "FAIL")
    ok = ok and ui_free

    def bases_of(items):
        return [item.base for item in items]

    def category_of(weapon):
        sid = weapon.player.name if weapon.player is not None else (
            weapon.gs.name if weapon.gs is not None else ""
        )
        return weapon_category(weapon.base, sid)

    anchor = "GunM16_ST" if "GunM16_ST" in bases else weapons[0].base
    filter_checks = [
        (bases_of(filter_weapons(weapons, "en", anchor)) == [anchor], "search by SID"),
        (anchor in bases_of(filter_weapons(weapons, "en", friendly_name(anchor, "en"))),
         "search by friendly name"),
        (anchor in bases_of(filter_weapons(weapons, "uk", friendly_name(anchor, "uk"))),
         "search uk by name"),
        (bases_of(filter_weapons(weapons, "en", "", "npc")) == [], "owner filter NPC"),
        (set(bases_of(filter_weapons(weapons, "en", "", "player"))) == bases,
         "owner filter player"),
        (bases_of(filter_weapons(weapons, "en", "", "all", "hg"))
         == bases_of(sort_weapons(
             [weapon for weapon in weapons if category_of(weapon) == "hg"],
             "alpha", "en")),
         "category filter pistols"),
        (weapon_category("GunViper_PP") == "smg", "_PP maps to smg"),
        (bases_of(filter_weapons(weapons, "en", "", "all", "all", "sid"))
         == sorted(bases, key=str.casefold), "sort by SID"),
        (bases_of(filter_weapons(weapons, "en", "", "all", "all", "modified"))
         == bases_of(sort_weapons(weapons, "alpha", "en")),
         "modified sort falls back to A-Z when clean"),
    ]
    for passed, label in filter_checks:
        print("  filter test:", label + ":", "OK" if passed else "FAIL")
        ok = ok and passed

    with tempfile.TemporaryDirectory() as workdir:
        player_copy = os.path.join(workdir, "player.cfg")
        gs_copy = os.path.join(workdir, "gs.cfg")
        shutil.copy2(PLAYER_CFG, player_copy)
        shutil.copy2(GS_CFG, gs_copy)
        pdoc = CfgDoc(player_copy)
        gdoc = CfgDoc(gs_copy)
        vanilla = CfgDoc(VANILLA_CHAR) if os.path.exists(VANILLA_CHAR) else None
        test_weapons = {
            weapon.base: weapon for weapon in build_weapons(pdoc, gdoc, vanilla)
        }
        anchor = anchor if anchor in test_weapons else next(iter(test_weapons))
        test_weapons[anchor].player_values["BaseDamage"] = "999999999.5"
        test_weapons[anchor].player_values["ArmorPiercing"] = "-3.25"
        vanilla_only = [
            base for base, weapon in test_weapons.items()
            if not weapon.player_is_patch and base != anchor
            and all(name in weapon.player_values for name in PLAYER_FIELDS)
        ]
        edit_base = vanilla_only[0] if vanilla_only else None
        untouched_base = vanilla_only[1] if len(vanilla_only) > 1 else None
        if edit_base is not None:
            test_weapons[edit_base].player_values["BaseDamage"] = "123.45"
        errors = validate_and_normalize(list(test_weapons.values()))
        if errors:
            print("  validation errors:", errors)
            ok = False
        apply_model_to_docs(list(test_weapons.values()), pdoc, gdoc)
        pdoc.save()
        gdoc.save()

        pdoc2 = CfgDoc(player_copy)
        gdoc2 = CfgDoc(gs_copy)
        vanilla2 = CfgDoc(VANILLA_CHAR) if os.path.exists(VANILLA_CHAR) else None
        saved = {
            weapon.base: weapon for weapon in build_weapons(pdoc2, gdoc2, vanilla2)
        }
        saved_sids = {sec.name for sec in pdoc2.sections()}
        anchor_ui = saved[anchor].player.find_scalar("DamageUI")
        checks = [
            (saved[anchor].player_values.get("BaseDamage") == "999999999.5",
             "no max clamp on stats"),
            (saved[anchor].player_values.get("ArmorPiercing") == "-3.25",
             "negative values accepted"),
            (not (set(AUTO_UI_FIELDS) & set(saved[anchor].player_values)),
             "UI bars never loaded as editable stats"),
        ]
        if edit_base is not None:
            checks += [
                (saved[edit_base].player_is_patch, "edited vanilla weapon gets a block"),
                (saved[edit_base].player_values.get("BaseDamage") == "123.45",
                 "added block keeps the edited value"),
                (edit_base in {base_sid(sid) for sid in saved_sids},
                 "added block is written to the patch"),
            ]
        if untouched_base is not None:
            checks += [
                (not saved[untouched_base].player_is_patch,
                 "untouched vanilla weapon stays out of the patch"),
                (untouched_base not in {base_sid(sid) for sid in saved_sids},
                 "no block for an unchanged weapon"),
            ]
        if vanilla is not None:
            checks.append((
                anchor_ui is not None
                and _to_number({"v": anchor_ui[2]}, "v") == 1.0,
                "damage bar capped with huge damage",
            ))
            if edit_base is not None:
                ref = vanilla_ui_baseline().get(saved[edit_base].player.name, {})
                acc = saved[edit_base].player.find_scalar("AccuracyUI")
                checks.append((
                    acc is not None
                    and _to_number(ref, "AccuracyUI") is not None
                    and abs(
                        _to_number({"v": acc[2]}, "v")
                        - _to_number(ref, "AccuracyUI")
                    ) < 1e-6,
                    "unchanged stat keeps the vanilla bar",
                ))
        checks += [
            (any("{bpatch}" in line for line in pdoc2.lines), "bpatch marker kept"),
            (pdoc2.lines[0].startswith("// GUR"), "comments kept"),
            (all(not line.strip().endswith(",")
                 for line in pdoc2.lines if not line.lstrip().startswith("//")),
             "no decimal commas"),
            (sum(1 for line in pdoc2.lines if "struct.begin" in line)
             == sum(1 for line in pdoc2.lines if "struct.end" in line),
             "struct balance kept"),
        ]
        for passed, label in checks:
            print("  edit test:", label + ":", "OK" if passed else "FAIL")
            ok = ok and passed

        if vanilla2 is not None:
            reset_p = CfgDoc(player_copy)
            reset_g = CfgDoc(gs_copy)
            reset_model = {
                weapon.base: weapon
                for weapon in build_weapons(reset_p, reset_g, CfgDoc(VANILLA_CHAR))
            }
            m16 = reset_model[anchor]
            for name in PLAYER_FIELDS:
                found = m16.vanilla.find_scalar(name)
                if found:
                    m16.player_values[name] = found[2]
            found = m16.vanilla.find_scalar("AlwaysPierce")
            if found:
                m16.player_bool = found[2].strip().lower() == "true"
            apply_model_to_docs(list(reset_model.values()), reset_p, reset_g)
            remaining = {sec.name for sec in reset_p.sections()}
            passed = (
                "GunM16_ST_Player" not in remaining
                and any(name.endswith("_Player_WS") for name in remaining)
            )
            print(
                "  edit test: vanilla-equal weapon loses its block:",
                "OK" if passed else "FAIL",
            )
            ok = ok and passed

        probe_path = os.path.join(workdir, "probe.cfg")
        with open(probe_path, "w", encoding="utf-8") as fh:
            fh.write(
                "GunZZProbe_AR_Player : struct.begin {bpatch}\n"
                "   BaseDamage = 40.0\n"
                "   DispersionRadius = 100.0\n"
                "   EffectiveFireDistanceMax = 2000.0\n"
                "   AccuracyUI = 0.50\n"
                "   DamageUI = 0.50\n"
                "   RangeUI = 0.50\n"
                "struct.end\n"
            )
        probe = Weapon("GunZZProbe_AR")
        probe.player = CfgDoc(probe_path).sections()[0]
        load_weapon_values(probe)
        probe.player_values.update(
            BaseDamage="20.0",
            DispersionRadius="200.0",
            EffectiveFireDistanceMax="1000.0",
        )
        ui = weapon_ui_values(probe, probe.player_values)
        probe_checks = [
            (ui.get("DamageUI") == "0.25", "damage bar halves with half damage"),
            (ui.get("AccuracyUI") == "0.25", "accuracy bar halves with double spread"),
            (ui.get("RangeUI") == "0.25", "range bar halves with half distance"),
        ]
        probe.player_values["BaseDamage"] = "999999.0"
        ui = weapon_ui_values(probe, probe.player_values)
        probe_checks.append(
            (ui.get("DamageUI") == "1.00", "damage bar capped at 1.0")
        )
        probe.player_values["BaseDamage"] = "-40.0"
        ui = weapon_ui_values(probe, probe.player_values)
        probe_checks.append(
            (ui.get("DamageUI") == "0.00", "damage bar clamped at 0")
        )
        for passed, label in probe_checks:
            print("  ui test:", label + ":", "OK" if passed else "FAIL")
            ok = ok and passed

        probe = {weapon.base: weapon for weapon in build_weapons(
            CfgDoc(player_copy), CfgDoc(gs_copy),
            CfgDoc(VANILLA_CHAR) if os.path.exists(VANILLA_CHAR) else None,
        )}
        probe["GunM16_ST"].player_values["BaseDamage"] = "123.5"
        modified_order = bases_of(filter_weapons(
            list(probe.values()), "en", "", "all", "all", "modified"
        ))
        passed = modified_order[0] == "GunM16_ST"
        print("  filter test: modified sort puts edited weapon first:",
              "OK" if passed else "FAIL")
        ok = ok and passed

        if os.path.exists(VANILLA_GS) and os.path.exists(VANILLA_CHAR):
            vdoc = CfgDoc(VANILLA_GS)
            target = next((s for s in vdoc.sections() if s.name == "GunM16_ST"), None)
            if target is None:
                print("  vanilla add test: FAIL (GunM16_ST missing in vanilla_gs)")
                ok = False
            else:
                block = build_gs_block(vdoc, target)
                append_block(gdoc2, block)
                gdoc2.save()
                added = {
                    weapon.base: weapon
                    for weapon in build_weapons(pdoc2, gdoc2, vanilla2)
                }
                merged = added["GunM16_ST"]
                passed = (
                    merged.gs is not None
                    and merged.gs.name == "GunM16_ST"
                    and merged.recoil_radius is not None
                    and merged.gs_values.get("MaxAmmo") is not None
                )
                print("  vanilla add test:",
                      "OK" if passed else "FAIL",
                      f"(gs={merged.gs is not None}, ammo={merged.gs_values.get('MaxAmmo')}, "
                      f"recoil={merged.recoil_radius})")
                ok = ok and passed
        else:
            print("  vanilla add test: SKIPPED (vanilla dumps missing)")

        remove_p = os.path.join(workdir, "remove_p.cfg")
        remove_g = os.path.join(workdir, "remove_g.cfg")
        shutil.copy2(PLAYER_CFG, remove_p)
        shutil.copy2(gs_copy, remove_g)
        rp = CfgDoc(remove_p)
        rg = CfgDoc(remove_g)
        removed_p = remove_section(rp, "GunM16_ST_Player")
        removed_g = remove_section(rg, "GunM16_ST")
        rp.save()
        rg.save()
        rp2 = CfgDoc(remove_p)
        rg2 = CfgDoc(remove_g)
        vanilla3 = CfgDoc(VANILLA_CHAR) if os.path.exists(VANILLA_CHAR) else None
        reset_weapons = {
            weapon.base: weapon for weapon in build_weapons(rp2, rg2, vanilla3)
        }
        m16 = reset_weapons.get("GunM16_ST")
        vanilla_m16 = None
        if vanilla3 is not None:
            sec = next(
                (s for s in vanilla3.sections() if s.name == "GunM16_ST_Player"), None
            )
            found = sec.find_scalar("BaseDamage") if sec is not None else None
            vanilla_m16 = found[2] if found else None
        ptext = "\n".join(rp2.lines)
        gtext = "\n".join(rg2.lines)
        reset_checks = [
            (removed_p and (removed_g or not rg.sections()),
             "reset removes the weapon blocks"),
            ("GunM16_ST_Player" not in {sec.name for sec in rp2.sections()},
             "reset removes player lines"),
            ("GunM16_ST" not in {sec.name for sec in rg2.sections()},
             "reset removes gs lines"),
            (vanilla3 is None or (
                m16 is not None and not m16.player_is_patch
                and m16.player_values.get("BaseDamage") == vanilla_m16),
             "reset weapon is back to vanilla stats"),
            (ptext.count("struct.begin") == ptext.count("struct.end")
             and gtext.count("struct.begin") == gtext.count("struct.end"),
             "reset keeps struct balance"),
            (rp2.lines[0].startswith("// GUR"), "reset keeps header comments"),
            (rp2.lines[-1] == "" and rp2.lines[-2].strip() == "struct.end",
             "reset keeps tidy player ending"),
            (rg2.lines[-1] == "", "reset keeps tidy gs ending"),
        ]
        for passed, label in reset_checks:
            print("  reset test:", label + ":", "OK" if passed else "FAIL")
            ok = ok and passed

        for name in [sec.name for sec in rp2.sections()]:
            remove_section(rp2, name)
        for name in [sec.name for sec in rg2.sections()]:
            remove_section(rg2, name)
        rp2.save()
        rg2.save()
        rp3 = CfgDoc(remove_p)
        rg3 = CfgDoc(remove_g)
        empty_checks = [
            (not rp3.sections() and not rg3.sections(), "reset can empty both files"),
            ("struct.end" not in "\n".join(rp3.lines)
             and "struct.end" not in "\n".join(rg3.lines),
             "reset leaves no dangling struct.end"),
        ]
        for passed, label in empty_checks:
            print("  reset test:", label + ":", "OK" if passed else "FAIL")
            ok = ok and passed

    print("SELFTEST", "OK" if ok else "FAILED")
    return 0 if ok else 1


def main() -> int:
    tests = "--selftest" in sys.argv or "--smoke" in sys.argv
    if tests and (sys.stdout is None or sys.stderr is None):
        # Windowed (frozen) builds have no console; keep test output visible.
        log_path = os.path.join(ROOT, "GUR_test.log")
        stream = open(log_path, "w", encoding="utf-8", buffering=1)
        sys.stdout = sys.stdout or stream
        sys.stderr = sys.stderr or stream
    if "--selftest" in sys.argv:
        return run_selftest()
    lang_override = None
    if "--lang" in sys.argv:
        index = sys.argv.index("--lang")
        if index + 1 < len(sys.argv):
            lang_override = sys.argv[index + 1]
    app = App(lang_override=lang_override)
    if "--smoke" in sys.argv:
        app.update()
        try:
            total = len(app.weapons)
            if total == 0 or app.listbox.size() != total:
                raise AssertionError(f"expected {total} weapons, got {app.listbox.size()}")
            if any(name in app.v_player for name in AUTO_UI_FIELDS):
                raise AssertionError("inventory UI fields must not be editable")
            probe_base = "GunM16_ST" if any(
                w.base == "GunM16_ST" for w in app.weapons
            ) else app.weapons[0].base
            app.search_var.set(probe_base)
            if [w.base for w in app.visible] != [probe_base]:
                raise AssertionError("search filter failed")
            app.search_var.set("")
            app.owner_combo.current(OWNER_KEYS.index("npc"))
            app.refresh_view()
            if app.visible:
                raise AssertionError("owner filter failed")
            app.owner_combo.current(0)
            app.cat_combo.current(CATEGORY_KEYS.index("hg"))
            app.refresh_view()
            expected_hg = [
                w.base for w in sort_weapons(
                    [w for w in app.weapons if weapon_category(w.base) == "hg"],
                    "alpha", app.lang,
                )
            ]
            if [w.base for w in app.visible] != expected_hg:
                raise AssertionError("category filter failed")
            app.cat_combo.current(0)
            app.sort_combo.current(SORT_KEYS.index("sid"))
            app.refresh_view()
            expected_sids = sorted((w.base for w in app.weapons), key=str.casefold)
            if [w.base for w in app.visible] != expected_sids:
                raise AssertionError("sort by SID failed")
            app.sort_combo.current(0)
            app.refresh_view()
            if app.listbox.size() != total:
                raise AssertionError("filter reset failed")
            if app.reset_btn.instate(["disabled"]):
                raise AssertionError("reset button should be enabled")
            if os.path.exists(VANILLA_CHAR) and os.path.exists(VANILLA_GS):
                docs = app._vanilla_docs()
                bases = {w.base for w in app.weapons}
                entries = [
                    (sec.name, "gs")
                    for sec in docs["gs"].sections()
                    if base_sid(sec.name) in bases
                ]
                dialog = AddWeaponDialog(
                    app, entries,
                    patch_bases=[w.base for w in app.weapons if w.gs is not None],
                )
                dialog.update()
                dialog.filter_var.set("AR416")
                dialog._refresh()
                if not dialog._items or any(
                    base_sid(sid) != "GunM16_ST" for sid, _kind in dialog._items
                ):
                    raise AssertionError("add dialog search failed")
                dialog.filter_var.set("")
                dialog.owner_combo.current(OWNER_KEYS.index("player"))
                dialog.cat_combo.current(CATEGORY_KEYS.index("hg"))
                dialog._refresh()
                if not dialog._items:
                    raise AssertionError("add dialog filters returned nothing")
                if any(
                    weapon_category(base_sid(sid), sid) != "hg"
                    for sid, _kind in dialog._items
                ):
                    raise AssertionError("add dialog filters failed")
                dialog.destroy()
        except AssertionError as exc:
            app.destroy()
            print("SMOKE FAILED:", exc)
            return 1
        app.after(300, app.destroy)
        app.mainloop()
        print("SMOKE OK")
        return 0
    app.mainloop()
    return 0


if __name__ == "__main__":
    sys.exit(main())
