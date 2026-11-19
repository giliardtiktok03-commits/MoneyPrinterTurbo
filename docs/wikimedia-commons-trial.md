# Wikimedia Commons API — First Test

This is an **experimental** integration, not a complete image-license manager.

## How to test

1. Start the MoneyPrinterTurbo Streamlit WebUI from this branch.
2. Under **Video Source**, select **Wikimedia Commons (historical images)** to test historical images directly, or **Automatic: Pexels > Pixabay > Coverr > Wikimedia** to test the fallback order.
3. Use a historically specific English search term such as `World War II aircraft 1943`.
4. Generate a short video. Review the generated clip(s), the task's material source manifest, and `wikimedia-audit.json` in the task directory.
5. You can also test API metadata without producing a video:

   ```bash
   python -m app.services.wikimedia_commons "World War II aircraft 1943"
   pytest test/services/test_wikimedia_commons.py -q
   ```

## Behavior and limitations

- Public Commons API requests do **not** need an API key.
- Wikimedia image searches call `action=query` with `generator=search`, `prop=imageinfo` and `extmetadata`.
- The first test **automatically uses CC0 only** when license name and URL match and no explicit restrictions are reported. CC BY, CC BY-SA, public-domain notices requiring jurisdiction-specific review, missing license metadata, and conflicting rights notices are not automatically used.
- Search audits include the candidates examined and their decisions. This does not certify a file for commercial use. Check any applicable personality, privacy, trademark or third-party rights separately.
- The automatic order tries stock providers **Pexels → Pixabay → Coverr**, then **Wikimedia Commons**. Unconfigured stock API keys are skipped. **Paid AI is not triggered automatically** in this test to avoid unexpected charges; select the existing AI provider explicitly for now.
- Images are rendered as short MP4 clips through the existing renderer; choose **Static Image** to avoid automatic zoom.
- This phase does **not** generate or insert YouTube image-credit blocks and does **not** enable automatic clearance for publication. Keep automatic YouTube publication disabled until the attribution and final-media audit module has been implemented.
- Other stock providers and existing AI providers remain intact.
