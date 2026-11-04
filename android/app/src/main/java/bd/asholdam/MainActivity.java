package bd.asholdam;

import android.app.Activity;
import android.content.ActivityNotFoundException;
import android.content.Intent;
import android.graphics.Color;
import android.net.Uri;
import android.os.Bundle;
import android.view.View;
import android.view.ViewGroup;
import android.webkit.CookieManager;
import android.webkit.WebChromeClient;
import android.webkit.WebResourceError;
import android.webkit.WebResourceRequest;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.widget.FrameLayout;

/**
 * Ashol Dam: the website, opened inside the app itself (no browser needed).
 * - Links to other sites (Daraz, Telegram, YouTube) open in their own apps or the browser.
 * - "Share → Ashol Dam" from the Daraz app opens the site with the shared link, which checks it.
 * - Back goes back a page; at the first page it closes the app.
 */
public class MainActivity extends Activity {
    private static final String HOST = "ashol-daam.vercel.app";
    private static final String HOME = "https://" + HOST + "/";

    private WebView web;

    @Override
    protected void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);

        FrameLayout root = new FrameLayout(this);
        root.setFitsSystemWindows(true);  // keep the page clear of the status bar and gesture bar
        root.setBackgroundColor(getResources().getColor(R.color.page, getTheme()));
        web = new WebView(this);
        web.setBackgroundColor(Color.TRANSPARENT);
        root.addView(web, new FrameLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.MATCH_PARENT));
        setContentView(root);

        WebSettings settings = web.getSettings();
        settings.setJavaScriptEnabled(true);
        settings.setDomStorageEnabled(true);  // remembered theme, saved copies
        settings.setMediaPlaybackRequiresUserGesture(true);
        // The site hides its "Install app" buttons when it sees this.
        settings.setUserAgentString(settings.getUserAgentString() + " AsholDamApp/1.1");
        CookieManager.getInstance().setAcceptCookie(true);  // your own "Recently checked" list
        CookieManager.getInstance().setAcceptThirdPartyCookies(web, false);

        web.setWebChromeClient(new WebChromeClient());  // lets the page show its "Are you sure?" boxes
        web.setWebViewClient(new WebViewClient() {
            @Override
            public boolean shouldOverrideUrlLoading(WebView view, WebResourceRequest request) {
                return openElsewhere(request.getUrl());
            }

            @Override
            public void onReceivedError(WebView view, WebResourceRequest request, WebResourceError error) {
                // No internet and nothing saved yet: say so instead of showing a browser error page.
                if (request.isForMainFrame()) {
                    view.loadDataWithBaseURL(HOME, OFFLINE_PAGE, "text/html", "utf-8", null);
                }
            }
        });

        if (savedInstanceState != null) {
            web.restoreState(savedInstanceState);
        } else {
            web.loadUrl(addressFor(getIntent()));
        }
    }

    @Override
    protected void onNewIntent(Intent intent) {
        super.onNewIntent(intent);  // shared again while the app is open
        setIntent(intent);
        web.loadUrl(addressFor(intent));
    }

    /** Which page to open: a shared Daraz link, a link to the site, or the home page. */
    private static String addressFor(Intent intent) {
        if (intent != null && Intent.ACTION_SEND.equals(intent.getAction())) {
            String text = intent.getStringExtra(Intent.EXTRA_TEXT);
            String title = intent.getStringExtra(Intent.EXTRA_SUBJECT);
            return HOME + "?source=app&text=" + Uri.encode(text == null ? "" : text)
                    + "&title=" + Uri.encode(title == null ? "" : title);
        }
        if (intent != null && Intent.ACTION_VIEW.equals(intent.getAction()) && intent.getData() != null
                && HOST.equals(intent.getData().getHost())) {
            return intent.getData().toString();
        }
        return HOME + "?source=app";
    }

    /** Pages of this site stay in the app; anything else opens in its own app or the browser. */
    private boolean openElsewhere(Uri uri) {
        if ("https".equals(uri.getScheme()) && HOST.equals(uri.getHost())) return false;
        try {
            startActivity(new Intent(Intent.ACTION_VIEW, uri));
        } catch (ActivityNotFoundException e) {
            // nothing on the phone can open it; stay put
        }
        return true;
    }

    @Override
    public void onBackPressed() {
        if (web.canGoBack()) web.goBack();
        else super.onBackPressed();
    }

    @Override
    protected void onSaveInstanceState(Bundle outState) {
        super.onSaveInstanceState(outState);
        web.saveState(outState);
    }

    @Override
    protected void onResume() {
        super.onResume();
        web.onResume();
    }

    @Override
    protected void onPause() {
        web.onPause();
        super.onPause();
    }

    @Override
    protected void onDestroy() {
        if (web != null) {
            ((ViewGroup) web.getParent()).removeView(web);
            web.destroy();
        }
        super.onDestroy();
    }

    private static final String OFFLINE_PAGE =
            "<!doctype html><meta name=viewport content='width=device-width,initial-scale=1'>"
            + "<style>body{margin:0;min-height:100vh;display:grid;place-items:center;font-family:sans-serif;"
            + "background:#ECE8DF;color:#22201C;text-align:center;padding:24px;box-sizing:border-box}"
            + "@media(prefers-color-scheme:dark){body{background:#151412;color:#ECE8DF}}"
            + "button{margin-top:16px;padding:10px 18px;border:1px solid currentColor;background:none;color:inherit;font-size:16px}</style>"
            + "<div><h2>No internet</h2><p>Ashol Dam needs the internet the first time.<br>"
            + "After that, products you've checked open offline too.</p>"
            + "<button onclick=\"location.href='" + HOME + "?source=app'\">Try again</button></div>";
}
