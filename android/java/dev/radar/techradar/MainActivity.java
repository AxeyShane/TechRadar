package dev.radar.techradar;

import android.app.Activity;
import android.content.SharedPreferences;
import android.os.Bundle;
import android.view.View;
import android.webkit.WebSettings;
import android.webkit.WebView;
import android.webkit.WebViewClient;
import android.webkit.WebChromeClient;
import android.widget.Button;
import android.widget.EditText;
import android.widget.LinearLayout;

public class MainActivity extends Activity {
    private WebView web;
    private LinearLayout serverBar;
    private EditText serverUrl;
    private SharedPreferences prefs;
    private static final String KEY_PREF = "server_url";

    @Override protected void onCreate(Bundle b) {
        super.onCreate(b);
        setContentView(R.layout.activity_main);
        prefs = getSharedPreferences("techradar", MODE_PRIVATE);

        web = findViewById(R.id.web);
        serverBar = findViewById(R.id.server_bar);
        serverUrl = findViewById(R.id.server_url);
        Button connect = findViewById(R.id.connect_btn);

        WebSettings st = web.getSettings();
        st.setJavaScriptEnabled(true);
        st.setDomStorageEnabled(true);
        st.setAllowFileAccess(true);
        st.setBuiltInZoomControls(true);
        st.setDisplayZoomControls(false);
        st.setUseWideViewPort(true);
        st.setLoadWithOverviewMode(true);
        st.setMediaPlaybackRequiresUserGesture(false);
        web.setWebViewClient(new WebViewClient());
        web.setWebChromeClient(new WebChromeClient());

        String saved = prefs.getString(KEY_PREF, "");
        serverUrl.setText(saved);
        if (!saved.isEmpty()) {
            connectServer(saved);
        }

        connect.setOnClickListener(new View.OnClickListener() {
            @Override public void onClick(View v) {
                String url = serverUrl.getText().toString().trim();
                connectServer(url);
            }
        });
    }

    private void connectServer(String url) {
        if (url.isEmpty()) return;
        if (!url.startsWith("http")) url = "http://" + url;
        prefs.edit().putString(KEY_PREF, url).apply();
        serverBar.setVisibility(View.GONE);
        web.loadUrl(url);
    }

    @Override public void onBackPressed() {
        if (web != null && web.canGoBack()) {
            web.goBack();
        } else {
            super.onBackPressed();
        }
    }
}
