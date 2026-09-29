import json
import os
from pathlib import Path
from zoneinfo import ZoneInfo

from google.adk.agents import Agent
from google.adk.apps import App
from google.adk.code_executors import AgentEngineSandboxCodeExecutor
from google.adk.models import Gemini
from google.genai import types

from a2ui.schema.manager import A2uiSchemaManager
from a2ui.basic_catalog.provider import BasicCatalog

from app.tools import get_dish_image
from app.a2ui_utils import a2ui_callback

METADATA_PATH = Path(__file__).resolve().parent.parent / "deployment_metadata.json"
sandbox_resource_name = os.environ.get("AGENT_ENGINE_SANDBOX_RESOURCE_NAME")
agent_engine_resource_name = os.environ.get("AGENT_ENGINE_RESOURCE_NAME")

if METADATA_PATH.exists():
    try:
        with open(METADATA_PATH) as f:
            metadata = json.load(f)
            sandbox_resource_name = sandbox_resource_name or metadata.get("sandbox_resource_name")
            agent_engine_resource_name = agent_engine_resource_name or metadata.get("remote_agent_runtime_id")
    except Exception:
        pass

if sandbox_resource_name:
    code_executor = AgentEngineSandboxCodeExecutor(sandbox_resource_name=sandbox_resource_name)
elif agent_engine_resource_name:
    code_executor = AgentEngineSandboxCodeExecutor(agent_engine_resource_name=agent_engine_resource_name)
else:
    code_executor = AgentEngineSandboxCodeExecutor()

MODEL = "gemini-3.6-flash"

schema_manager = A2uiSchemaManager(
    version="0.8",
    catalogs=[BasicCatalog.get_config("0.8")],
)

instruction = schema_manager.generate_system_prompt(
    role_description="You are a Menu Translator assistant for travelers.",
    workflow_description=(
        "If the user uploads an image of a menu, analyze the picture directly and extract the main dishes. "
        "For each dish, write a short description (1-2 sentences) and determine whether it is [Non-Vegetarian], [Vegetarian], or [Vegan] based entirely on your language and visual knowledge. "
        "Categorize ALL dishes into exactly three groups: [Non-Vegetarian], [Vegetarian], and [Vegan]. "
        "You MUST output the response as a valid A2UI JSON array. "
        "Output an overview list of the categorized dishes as an A2UI layout using Column and Text components. "
        "CRITICAL REQUIREMENT: Every single dish MUST be placed in its OWN SEPARATE Text component. "
        "NEVER combine multiple dishes into a single paragraph or bulleted text block. "
        "For each dish, create a dedicated Text component with text formatted as: `Dish Name: Short description`. "
        "For category headers, create dedicated Text components with usageHint 'h2' or 'h3' (e.g. `🥩 Non-Vegetarian`, `🥗 Vegetarian`, `🌱 Vegan`). "
        "Do not fetch images during the overview step. "
        "If the user asks for details or a picture of a specific dish, use the `get_dish_image` tool to fetch its photo URL. "
        "Then, return an A2UI Card showing the Image component (with the fetched URL), followed by the dish name, description, and dietary category in Text components."
    ),
    ui_description=(
        "Keep every surface tiny and flat: ONE Card > ONE Column > individual Text rows. "
        "Never nest a Card inside a Card. "
        "Use ONLY these components: Card, Column, Row, Text, and Image. Do not use "
        "Table or Heading (unsupported), or Buttons, actions, or forms (they do "
        "nothing in adk web). "
        "Every dish must be its own Text row with its own ID (e.g. 'dish_paneer_tikka'). "
        "You may include one Image component, but only when you have a public https "
        "URL for the image. Set the Image url to that exact https link. "
        "CRITICAL: Output ONLY the raw A2UI JSON array starting with `[` and ending with `]`. "
        "Do NOT output any markdown, prose, conversational text, or explanation before or after the JSON."
    ),
    include_schema=True,
    include_examples=True,
)

root_agent = Agent(
    name="root_agent",
    model=Gemini(
        model=MODEL,
        retry_options=types.HttpRetryOptions(attempts=3),
    ),
    instruction=instruction,
    tools=[get_dish_image],
    code_executor=code_executor,
    after_model_callback=a2ui_callback,
)

app = App(
    root_agent=root_agent,
    name="app",
)
