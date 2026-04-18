    """Auto-generated Playwright demo script for: The R P I Workflow using HVE in VS Code"""

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
# --- Section: Installing the HVE Extension in VS Code ---
elapsed_ms = (time.time() - recording_start) * 1000
remaining = max(0, 22150 - elapsed_ms)
# visual: VS Code Extensions sidebar with 'HVE Core' in the search bar and highlighted in the results
page.wait_for_timeout(int(remaining))  # install-shot-1
# visual: VS Code Extensions sidebar with 'HVE Core' selected and blue Install button visible
page.wait_for_timeout(20000)  # install-shot-2
# visual: VS Code editor with confirmation pop-up for HVE Core install; Copilot Chat panel icon becomes visible
page.wait_for_timeout(20000)  # install-shot-3
# --- Section: Using @task-researcher to Explore Titanic Dataset ---
elapsed_ms = (time.time() - recording_start) * 1000
remaining = max(0, 67350 - elapsed_ms)
# visual: VS Code Copilot Chat panel with @task-researcher agent selected in the picker
page.wait_for_timeout(int(remaining))  # research-shot-1
# visual: Copilot Chat input box with 'Explore titanic.csv, summarize columns, and give key insights for data science.' typed in
page.wait_for_timeout(15000)  # research-shot-2
# visual: VS Code Explorer sidebar with .copilot-tracking folder open, research markdown file visible with summary of titanic.csv
page.wait_for_timeout(35000)  # research-shot-3
# --- Section: Planning with @task-planner Agent ---
elapsed_ms = (time.time() - recording_start) * 1000
remaining = max(0, 113650 - elapsed_ms)
# visual: Copilot Chat panel with @task-planner agent selected
page.wait_for_timeout(int(remaining))  # planner-shot-1
# visual: Chat input box with prompt: 'Plan a data science workflow to load titanic.csv, explore it, and build a simple model predicting survival.'
page.wait_for_timeout(10000)  # planner-shot-2
# visual: VS Code Explorer sidebar with .copilot-tracking folder, planning markdown file open, step-by-step workflow highlighted
page.wait_for_timeout(25000)  # planner-shot-3
# --- Section: Implementing with @task-implementer – Load, Explore, and Model Titanic Data ---
elapsed_ms = (time.time() - recording_start) * 1000
remaining = max(0, 158200 - elapsed_ms)
# visual: Copilot Chat panel with @task-implementer agent selected
page.wait_for_timeout(int(remaining))  # implementer-shot-1
# visual: Chat input box with prompt: 'Write Python code to load titanic.csv, explore the data, and build a simple logistic regression predicting Survived.'
page.wait_for_timeout(10000)  # implementer-shot-2
# visual: VS Code Explorer sidebar showing new file explore_titanic.py, file open with Python code
page.wait_for_timeout(15000)  # implementer-shot-3
# visual: VS Code terminal panel running 'python explore_titanic.py', script output showing summary stats and model score
page.wait_for_timeout(40000)  # implementer-shot-4
# --- Section: RPI-Agent: A Shortcut for Simple Workflows ---
elapsed_ms = (time.time() - recording_start) * 1000
remaining = max(0, 213150 - elapsed_ms)
# visual: Copilot Chat panel with @RPI-agent agent selected, prompt entered, output shown
page.wait_for_timeout(int(remaining))  # rpi-agent-shot-1

            context.close()
            browser.close()


    if __name__ == "__main__":
        main()
