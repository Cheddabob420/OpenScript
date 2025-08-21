#!/usr/bin/env python3
"""
OpenCV + Selenium example script

Flows:
 - Setup: open Google, take a screenshot, let the user draw a rectangle around the logo to save a template.
 - Check: open Google, take a screenshot, run multi-scale template matching to find the saved logo template.
   If found, draw a red box on the screenshot, save an annotated copy, and show both a desktop notification
   (using notify-send) and a browser alert.

Notes:
 - Requires a graphical session for interactive ROI selection (cv2.selectROI) and for opening the browser.
 - Uses webdriver-manager to automatically obtain ChromeDriver.
"""

import argparse
import subprocess
import yaml
import sys
import time
import tempfile
import atexit
import shutil
from pathlib import Path

import cv2
import numpy as np
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.chrome.options import Options
from webdriver_manager.chrome import ChromeDriverManager


ROOT = Path(__file__).resolve().parent
DATA_DIR = ROOT / "data"
SCREENSHOT = DATA_DIR / "google.png"
TEMPLATE = DATA_DIR / "google_logo.png"
ANNOTATED = DATA_DIR / "google_annotated.png"


def ensure_dirs():
	DATA_DIR.mkdir(parents=True, exist_ok=True)


def open_google_and_screenshot(url: str = "https://www.google.com", output_path: Path = SCREENSHOT, headless: bool = False):
	"""Open the URL in Chrome via Selenium and save a full-page screenshot to output_path.

	Returns the webdriver instance (caller should quit it) so we can run execute_script for alerts when needed.
	"""
	chrome_options = Options()
	# Prefer a visible browser during setup so the user can interact; allow headless for servers if requested
	if headless:
		chrome_options.add_argument("--headless=new")
		chrome_options.add_argument("--window-size=1920,1080")
	else:
		chrome_options.add_argument("--start-maximized")

	# Some environments need these flags
	chrome_options.add_argument("--disable-gpu")
	chrome_options.add_argument("--no-sandbox")
	chrome_options.add_argument("--disable-dev-shm-usage")
	chrome_options.add_argument("--no-first-run")
	chrome_options.add_argument("--no-default-browser-check")
	chrome_options.add_argument("--disable-extensions")

	# Use a temporary user data dir to avoid 'profile in use' errors when multiple
	# Chrome instances are launched. We register cleanup at process exit.
	tmp_profile = tempfile.mkdtemp(prefix="ops_chrome_profile_")
	chrome_options.add_argument(f"--user-data-dir={tmp_profile}")
	atexit.register(lambda: shutil.rmtree(tmp_profile, ignore_errors=True))

	service = Service(ChromeDriverManager().install())
	driver = webdriver.Chrome(service=service, options=chrome_options)
	driver.get(url)
	time.sleep(2)  # let page load; adjust as needed

	# save screenshot
	output_path_parent = output_path.parent
	output_path_parent.mkdir(parents=True, exist_ok=True)
	driver.save_screenshot(str(output_path))
	return driver


def select_logo_interactive(image_path: Path, template_out: Path):
	"""Open the screenshot and let user draw a rectangle around the logo; save template_out."""
	img = cv2.imread(str(image_path))
	if img is None:
		raise FileNotFoundError(f"Cannot read screenshot {image_path}")

	# Let the user pick ROI (requires GUI)
	r = cv2.selectROI("Select logo and press ENTER or SPACE", img, showCrosshair=True, fromCenter=False)
	cv2.destroyAllWindows()

	x, y, w, h = [int(v) for v in r]
	if w == 0 or h == 0:
		raise RuntimeError("No region selected")

	logo = img[y : y + h, x : x + w]
	cv2.imwrite(str(template_out), logo)
	print(f"Saved logo template to {template_out}")


def capture_logo_by_dom(driver: webdriver.Chrome, template_out: Path):
	"""Try to find the Google logo element in the page and crop the saved screenshot accordingly.
	This is a non-interactive fallback for headless or environments without OpenCV GUI support.
	"""
	# take sure a screenshot exists
	if not SCREENSHOT.exists():
		driver.save_screenshot(str(SCREENSHOT))

	# try several selectors commonly used for Google's logo
	selectors = [
		'img[alt="Google"]',
		'img#hplogo',
		'div#lga img',
		'img[alt^="Google"]',
	]

	el = None
	for sel in selectors:
		try:
			el = driver.find_element(By.CSS_SELECTOR, sel)
			if el:
				break
		except Exception:
			el = None

	if el is None:
		# fallback: inspect all <img> tags and pick the most likely Google logo
		imgs = driver.find_elements(By.TAG_NAME, "img")
		best = None
		best_score = -1
		for e in imgs:
			try:
				alt = (e.get_attribute("alt") or "").lower()
				src = (e.get_attribute("src") or "").lower()
				loc = e.location
				size = e.size
			except Exception:
				continue

			score = 0
			if "google" in alt:
				score += 50
			if "google" in src:
				score += 30
			# prefer images near the top of the page
			y = loc.get("y", 0)
			score += max(0, 50 - int(y / 5))
			# moderate preference for typical logo width
			w = int(size.get("width", 0))
			if 10 < w < 600:
				score += 10

			if score > best_score:
				best_score = score
				best = (e, loc, size)

		if best is None or best_score < 10:
			raise RuntimeError("Failed to locate Google logo element via DOM heuristics")

		el, loc, size = best

	# get precise bounding box and devicePixelRatio from the browser
	# Prefer Selenium's element screenshot if available (handles DPR and viewport correctly)
	try:
		el.screenshot(str(template_out))
		print(f"Saved logo template to {template_out} via element.screenshot()")
		return
	except Exception:
		# element.screenshot may fail on some drivers; fall back to boundingClientRect
		try:
			rect = driver.execute_script(
				"var r = arguments[0].getBoundingClientRect(); return {x: r.left, y: r.top, w: r.width, h: r.height, dpr: window.devicePixelRatio || 1};",
				el,
			)
		except Exception:
			# fallback to Selenium location/size
			loc = el.location
			size = el.size
			rect = {"x": loc.get("x", 0), "y": loc.get("y", 0), "w": size.get("width", 0), "h": size.get("height", 0), "dpr": 1}

	# get a full-page screenshot as PNG bytes (handles DPR correctly for most drivers)
	png = driver.get_screenshot_as_png()
	arr = np.frombuffer(png, dtype=np.uint8)
	img = cv2.imdecode(arr, cv2.IMREAD_COLOR)
	if img is None:
		raise RuntimeError("Failed to decode driver screenshot PNG")

	dpr = float(rect.get("dpr", 1))
	x = int(rect["x"] * dpr)
	y = int(rect["y"] * dpr)
	w = int(rect["w"] * dpr)
	h = int(rect["h"] * dpr)

	# Ensure within bounds and integer
	x = max(0, min(img.shape[1] - 1, x))
	y = max(0, min(img.shape[0] - 1, y))
	x2 = max(0, min(img.shape[1], x + max(1, w)))
	y2 = max(0, min(img.shape[0], y + max(1, h)))

	logo = img[y:y2, x:x2]
	if logo.size == 0:
		# dump debug info to help diagnose
		print(f"DOM crop debug: img.shape={img.shape}, rect={rect}, computed box={(x,y,x2,y2)}")
		raise RuntimeError("Cropped logo has zero size")

	cv2.imwrite(str(template_out), logo)
	print(f"Saved logo template to {template_out} via DOM capture (score={best_score})")


def multi_scale_template_match(screenshot: np.ndarray, template: np.ndarray, scales=None, method=cv2.TM_CCOEFF_NORMED):
	"""Multi-scale template matching: returns best (max_val, top_left, (w,h))"""
	if scales is None:
		scales = np.linspace(0.5, 1.5, 21)

	best_val = -1
	best_loc = None
	best_size = (template.shape[1], template.shape[0])

	for s in scales:
		new_w = max(1, int(template.shape[1] * s))
		new_h = max(1, int(template.shape[0] * s))
		resized = cv2.resize(template, (new_w, new_h), interpolation=cv2.INTER_AREA)

		if resized.shape[0] > screenshot.shape[0] or resized.shape[1] > screenshot.shape[1]:
			continue

		res = cv2.matchTemplate(screenshot, resized, method)
		min_val, max_val, min_loc, max_loc = cv2.minMaxLoc(res)

		# For TM_CCOEFF_NORMED higher is better
		val = max_val
		if val > best_val:
			best_val = val
			best_loc = max_loc
			best_size = (resized.shape[1], resized.shape[0])

	return best_val, best_loc, best_size


def notify_desktop(title: str, message: str):
	# Linux: use notify-send if available
	try:
		subprocess.run(["notify-send", title, message])
	except FileNotFoundError:
		print("notify-send not available; skipping desktop notification")


def main():
	parser = argparse.ArgumentParser(description="Google logo template detector (OpenCV + Selenium)")
	parser.add_argument("--setup", action="store_true", help="Run setup: open Google, let user select logo to save")
	parser.add_argument("--headless", action="store_true", help="Run browser headless (useful for servers)")
	parser.add_argument("--threshold", type=float, default=None, help="Matching threshold (0-1) to consider a hit")
	parser.add_argument("--config", type=str, help="Path to YAML config to automate variables and flows")

	args = parser.parse_args()
	ensure_dirs()

	cfg = None
	if args.config:
		with open(args.config, "r") as f:
			cfg = yaml.safe_load(f)

	# Helper to get config values with fallback to CLI/defaults
	def cget(key, default=None):
		return (cfg or {}).get(key, default)

	# Decide final runtime parameters
	url = cget("url", "https://www.google.com")
	headless = args.headless or cget("headless", False)
	threshold = args.threshold if args.threshold is not None else cget("threshold", 0.78)

	# Allow config to override paths
	global SCREENSHOT, TEMPLATE, ANNOTATED
	SCREENSHOT = Path(cget("screenshot", str(SCREENSHOT)))
	TEMPLATE = Path(cget("template", str(TEMPLATE)))
	ANNOTATED = Path(cget("annotated", str(ANNOTATED)))

	auto_setup = cget("auto_setup", "if_missing")

	def run_setup():
		print("Setup: opening URL and taking a screenshot for ROI selection...")
		driver = open_google_and_screenshot(url=url, headless=headless)
		try:
			try:
				select_logo_interactive(SCREENSHOT, TEMPLATE)
			except cv2.error:
				print("OpenCV GUI not available or failed; attempting DOM-based logo capture...")
				try:
					capture_logo_by_dom(driver, TEMPLATE)
				except Exception as dom_e:
					print(f"DOM capture failed: {dom_e}")
					raise
		finally:
			driver.quit()
		print("Setup complete. Later run without --setup to detect the logo and trigger notifications.")

	# Auto-setup logic
	if args.setup:
		run_setup()
		return

	if auto_setup == "always" or (auto_setup == "if_missing" and not TEMPLATE.exists()):
		try:
			run_setup()
		except Exception as e:
			print(f"Auto-setup failed: {e}")

	# Default: check mode
	if not TEMPLATE.exists():
		print(f"No template found at {TEMPLATE}. Run with --setup or provide a config to create the logo template.")
		sys.exit(1)

	print("Opening URL and taking screenshot for detection...")
	driver = open_google_and_screenshot(url=url, headless=headless)
	try:
		img = cv2.imread(str(SCREENSHOT))
		template = cv2.imread(str(TEMPLATE))
		if img is None or template is None:
			raise RuntimeError("Failed to read screenshot or template")

		scales = cget("scales", None)
		best_val, best_loc, (w, h) = multi_scale_template_match(img, template, scales=scales)
		print(f"Best match value: {best_val:.3f}")

		success = best_val >= threshold and best_loc is not None

		if success:
			top_left = best_loc
			bottom_right = (top_left[0] + w, top_left[1] + h)
			# draw red rectangle
			annotated = img.copy()
			cv2.rectangle(annotated, top_left, bottom_right, (0, 0, 255), 3)
			cv2.imwrite(str(ANNOTATED), annotated)
			print(f"Logo found (val={best_val:.3f}). Annotated screenshot saved to {ANNOTATED}")

			# Desktop notification
			notify_desktop("Logo detected", f"Match score: {best_val:.3f}")

			# Browser alert
			try:
				driver.execute_script("alert('Logo detected by OpenCV');")
				time.sleep(1)
				try:
					alert = driver.switch_to.alert
					alert.accept()
				except Exception:
					pass
			except Exception as e:
				print(f"Failed to show browser alert: {e}")

			# optional configured success command
			cmd = cget("on_detect_success", None)
			if cmd:
				try:
					subprocess.run(cmd, shell=True)
				except Exception as e:
					print(f"Failed to run success command: {e}")

		else:
			print("Logo not found (below threshold).")
			cmd = cget("on_detect_failure", None)
			if cmd:
				try:
					subprocess.run(cmd, shell=True)
				except Exception as e:
					print(f"Failed to run failure command: {e}")

	finally:
		driver.quit()


if __name__ == '__main__':
	main()