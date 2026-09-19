# AI Blog Hugo

Manual English content pipeline for Catholic religious gifts, rosary beads, and B2B wholesale buyers. Generated content is validated before it can be committed or deployed.

Website: https://rosarysupply.com/

## How It Works

```
Manual trigger → DeepSeek API generates article → Hugo builds site → GitHub Pages deploys
```

## Quick Start (5 minutes)

### 1. Fork This Repository

Click **Fork** on the top right of this page.

### 2. Add Your API Key

Go to your forked repo → **Settings → Secrets and variables → Actions → New repository secret**

| Secret Name | Value |
|------------|-------|
| `OPENAI_API_KEY` | Your DeepSeek or OpenAI API key |
| `AI_MODEL` | `deepseek-chat` (for DeepSeek) or `gpt-3.5-turbo` (for OpenAI) |
| `AI_API_URL` | `https://api.deepseek.com/v1` (for DeepSeek) |
| `PEXELS_API_KEY` | Optional Pexels API key for featured images |

### 3. Edit blog-config.yaml

Open `blog-config.yaml` in your repo and customize:

- **alibaba_store_url**: Your Alibaba store URL
- **alibaba_products**: Your approved product URLs
- **business_facts**: Verified MOQ and product claims the AI is allowed to state
- **keywords**: Add your long-tail keywords (50+ recommended)

### 4. Run GitHub Actions Manually

Go to **Actions → Generate Blog Post → Run workflow** when you want to generate a new article. Scheduled auto-publishing is disabled.

### 5. Enable GitHub Pages

Go to **Settings → Pages → Source: Deploy from a branch → gh-pages / (root)**

### 6. Verify the Manual Publish

The workflow generates, validates, commits, and deploys the article only when manually triggered.

Wait 2-5 minutes, then check your site at `https://yourusername.github.io/AI-AutoBlog-Hugo/`

## Features

- **Manual publishing**: Articles are generated only when the workflow is manually run
- **B2B SEO optimized**: Prompts tuned for wholesale buyer intent
- **Alibaba traffic引流**: Sidebar + article footer + inline links
- **Featured images**: AI-generated or stock images for each article
- **SEO ready**: Hugo static site, fast loading, Google-friendly
- **Review mode**: Optional PR-based review before publishing
- **FAQ Schema**: Articles include FAQ sections for rich snippets

## File Structure

```
├── .github/workflows/
│   └── auto-generate-post.yml    # Manual generation workflow
├── blog-config.yaml                # Keywords, links, and verified business facts
├── layouts/
│   ├── partials/
│   │   └── alibaba-banner.html     # Sidebar Alibaba banner
│   └── _default/
│       └── single.html            # Article page with footer link
├── content/posts/                  # Generated articles go here
├── scripts/
│   ├── generate-post.py            # Post generation script
│   └── validate-site.py            # Content safety validation
├── static/                         # Static assets
└── requirements.txt               # Locked Python dependencies
```

## Customization

### Change Article Style

Edit the prompt builders in `scripts/generate-post.py`.

### Change Theme

Update the Hugo configuration under `config/_default/` and pin the corresponding theme commit in the workflow.

### Publish an Article

Scheduled automatic publishing has been removed. To publish a new article, open **Actions → Generate Blog Post → Run workflow**. The workflow validates the generated content before committing and deploying it. Product recommendation posts can be generated through **Actions → Generate Product Recommendation → Run workflow**.

## Cost

- **GitHub Pages**: Free
- **GitHub Actions**: Included with GitHub, with usage depending on how often you publish manually
- **DeepSeek API**: ~$0.01-0.02 per article (1200 words)
- **Total**: Pay only for the articles you choose to generate manually

## Bind Custom Domain

1. Add a `CNAME` file in `static/` with your domain
2. Configure your domain DNS: CNAME → `yourusername.github.io`
3. In repo Settings → Pages → Custom domain: enter your domain

## License

MIT License - Free to use, modify, and distribute.
