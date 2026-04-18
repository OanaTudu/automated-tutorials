    """Auto-generated Playwright demo script for: HyperVelocity Engineering VS Code extension - installation, agents, and AI-native data science workflows"""

    import sys
    import time
    from pathlib import Path
    from playwright.sync_api import sync_playwright


    def main() -> None:
        video_dir = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(".")
        with sync_playwright() as pw:
            browser = pw.chromium.launch(headless=False)
            context = browser.new_context(
                viewport={"width": 1280, "height": 720},
                record_video_dir=str(video_dir),
                record_video_size={"width": 1280, "height": 720},
            )
            page = context.new_page()

        recording_start = time.time()
# --- Section: Install HyperVelocity Engineering Extension ---
elapsed_ms = (time.time() - recording_start) * 1000
remaining = max(0, 22150 - elapsed_ms)
# visual: VS Code Extensions sidebar with search bar reading 'HyperVelocity Engineering'
page.wait_for_timeout(int(remaining))  # s1-1
# visual: VS Code Extensions list showing HyperVelocity Engineering extension with 'Install' button
page.wait_for_timeout(20000)  # s1-2
# visual: VS Code showing HVE extension as installed in side panel
page.wait_for_timeout(15000)  # s1-3
# --- Section: Meet the Agents: Open the Copilot Chat Panel ---
elapsed_ms = (time.time() - recording_start) * 1000
remaining = max(0, 48600 - elapsed_ms)
# visual: VS Code sidebar with Copilot Chat icon highlighted
page.wait_for_timeout(int(remaining))  # s2-1
# visual: VS Code Copilot Chat panel with agent picker showing @task-researcher, @task-planner, @task-implementer
page.wait_for_timeout(20000)  # s2-2
# --- Section: Step 1: Research with @task-researcher ---
elapsed_ms = (time.time() - recording_start) * 1000
remaining = max(0, 76700 - elapsed_ms)
# visual: VS Code Copilot Chat panel with @task-researcher selected
page.wait_for_timeout(int(remaining))  # s3-1
# visual: VS Code Copilot Chat with the prompt 'Explore titanic.csv and summarize the data'
page.wait_for_timeout(15000)  # s3-2
# visual: VS Code Explorer showing .copilot-tracking/research/{date}/titanic-research.md
page.wait_for_timeout(35000)  # s3-3
# --- Section: Step 2: Planning with @task-planner ---
elapsed_ms = (time.time() - recording_start) * 1000
remaining = max(0, 105950 - elapsed_ms)
# visual: VS Code Copilot Chat panel with @task-planner selected
page.wait_for_timeout(int(remaining))  # s4-1
# visual: VS Code Copilot Chat with prompt 'Plan a Python script to load, explore, and predict survival on titanic.csv'
page.wait_for_timeout(10000)  # s4-2
# visual: VS Code Explorer showing .copilot-tracking/plans/{date}/titanic-plan.instructions.md
page.wait_for_timeout(30000)  # s4-3
# --- Section: Step 3: Implement with @task-implementer ---
elapsed_ms = (time.time() - recording_start) * 1000
remaining = max(0, 136950 - elapsed_ms)
# visual: VS Code Copilot Chat panel with @task-implementer selected
page.wait_for_timeout(int(remaining))  # s5-1
# visual: VS Code Copilot Chat with 'Implement the plan for titanic.csv analysis in Python' prompt
page.wait_for_timeout(15000)  # s5-2
# visual: VS Code Explorer showing .copilot-tracking/details/{date}/titanic-details.md and script file open
page.wait_for_timeout(20000)  # s5-3
# visual: VS Code editor with titanic.py open and 'Run Python File' button highlighted; terminal panel showing script output
page.wait_for_timeout(25000)  # s5-4

            context.close()
            browser.close()


    if __name__ == "__main__":
        main()
