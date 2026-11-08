package dev.handlink.mobile;

import android.Manifest;
import android.content.pm.PackageManager;
import android.graphics.Bitmap;
import android.graphics.Color;
import android.graphics.Matrix;
import android.graphics.Typeface;
import android.graphics.drawable.GradientDrawable;
import android.os.Bundle;
import android.os.SystemClock;
import android.text.InputType;
import android.view.Gravity;
import android.view.View;
import android.view.WindowManager;
import android.widget.Button;
import android.widget.EditText;
import android.widget.FrameLayout;
import android.widget.LinearLayout;
import android.widget.TextView;

import androidx.annotation.NonNull;
import androidx.activity.ComponentActivity;
import androidx.camera.core.CameraSelector;
import androidx.camera.core.ImageAnalysis;
import androidx.camera.core.ImageProxy;
import androidx.camera.core.Preview;
import androidx.camera.lifecycle.ProcessCameraProvider;
import androidx.camera.view.PreviewView;
import androidx.core.content.ContextCompat;

import com.google.common.util.concurrent.ListenableFuture;
import com.google.mediapipe.framework.image.BitmapImageBuilder;
import com.google.mediapipe.framework.image.MPImage;
import com.google.mediapipe.tasks.core.BaseOptions;
import com.google.mediapipe.tasks.vision.core.RunningMode;
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarker;
import com.google.mediapipe.tasks.vision.handlandmarker.HandLandmarkerResult;
import com.google.mediapipe.tasks.components.containers.NormalizedLandmark;

import org.json.JSONArray;
import org.json.JSONObject;

import java.net.DatagramPacket;
import java.net.DatagramSocket;
import java.net.InetAddress;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;
import java.util.List;
import java.util.concurrent.ExecutorService;
import java.util.concurrent.Executors;

/**
 * Entirely on-device hand inference. Only 21-point landmark packets, not
 * camera frames, are transmitted to a trusted local PC using UDP.
 */
public final class MainActivity extends ComponentActivity {
    private static final int BG = Color.rgb(8,13,19);
    private static final int PANEL = Color.rgb(16,25,35);
    private static final int EDGE = Color.rgb(43,61,76);
    private static final int MINT = Color.rgb(140,247,203);
    private static final int WHITE = Color.rgb(237,247,243);
    private static final int MUTED = Color.rgb(150,171,183);
    private final ExecutorService cameraWorker = Executors.newSingleThreadExecutor();
    private final ExecutorService networkWorker = Executors.newSingleThreadExecutor();
    private PreviewView preview;
    private HandOverlay overlay;
    private EditText ipInput;
    private EditText codeInput;
    private TextView state;
    private TextView stats;
    private Button connectButton;
    private Button flipButton;
    private ProcessCameraProvider provider;
    private HandLandmarker landmarker;
    private boolean front = true;
    private volatile boolean sending = false;
    private volatile boolean paired = false;
    private volatile DatagramSocket udp;
    private volatile InetAddress pcAddress;
    private volatile String pairCode = "";
    private int seq = 0;
    private long lastPreviewUpdate = 0;
    private long lastFpsUpdate = 0;
    private int frames = 0;
    private long lastAck = 0;

    @Override public void onCreate(Bundle savedInstanceState) {
        super.onCreate(savedInstanceState);
        getWindow().setStatusBarColor(BG);
        getWindow().setNavigationBarColor(BG);
        getWindow().addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON);
        buildUi();
        try {
            BaseOptions base = BaseOptions.builder().setModelAssetPath("hand_landmarker.task").build();
            HandLandmarker.HandLandmarkerOptions options = HandLandmarker.HandLandmarkerOptions.builder()
                .setBaseOptions(base)
                .setRunningMode(RunningMode.LIVE_STREAM)
                .setNumHands(2)
                .setMinHandDetectionConfidence(.5f)
                .setMinHandPresenceConfidence(.5f)
                .setMinTrackingConfidence(.5f)
                .setResultListener((result, input) -> onLandmarks(result))
                .setErrorListener(error -> runOnUiThread(() -> status("TRACKER ERROR: " + error.getMessage(), false)))
                .build();
            landmarker = HandLandmarker.createFromOptions(this, options);
            status("TRACKER READY · GRANT CAMERA PERMISSION", false);
        } catch (Exception ex) {
            status("MODEL ERROR: " + ex.getMessage(), false);
            return;
        }
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED)
            requestPermissions(new String[]{Manifest.permission.CAMERA}, 100);
        else startCamera();
    }

    private GradientDrawable rounded(int color, int border, int dp) {
        GradientDrawable g = new GradientDrawable();
        g.setColor(color); g.setCornerRadius(dip(dp));
        if (border != 0) g.setStroke(dip(1), border);
        return g;
    }
    private int dip(int d) { return Math.round(d * getResources().getDisplayMetrics().density); }

    private TextView text(String value, int sp, int color, boolean bold) {
        TextView v = new TextView(this);
        v.setText(value); v.setTextSize(sp); v.setTextColor(color);
        if (bold) v.setTypeface(Typeface.DEFAULT, Typeface.BOLD);
        return v;
    }
    private Button button(String label, boolean accent) {
        Button b = new Button(this);
        b.setText(label); b.setTextSize(12); b.setAllCaps(false);
        b.setTextColor(accent ? BG : WHITE);
        b.setBackground(rounded(accent ? MINT : PANEL, accent ? 0 : EDGE, 12));
        b.setPadding(dip(12), dip(8), dip(12), dip(8));
        return b;
    }
    private EditText input(String hint, String initial) {
        EditText edit = new EditText(this);
        edit.setSingleLine(true); edit.setText(initial); edit.setHint(hint);
        edit.setTextSize(16); edit.setTextColor(WHITE); edit.setHintTextColor(MUTED);
        edit.setSelectAllOnFocus(true);
        edit.setBackground(rounded(BG, EDGE, 9));
        edit.setPadding(dip(12), dip(12), dip(12), dip(12));
        return edit;
    }

    private void buildUi() {
        LinearLayout screen = new LinearLayout(this);
        screen.setOrientation(LinearLayout.VERTICAL);
        screen.setBackgroundColor(BG);
        setContentView(screen);
        LinearLayout heading = new LinearLayout(this);
        heading.setOrientation(LinearLayout.VERTICAL); heading.setPadding(dip(18), dip(15), dip(18), dip(12));
        heading.addView(text("●  HANDLINK  /  CAMERA", 22, MINT, true));
        heading.addView(text("WIRELESS HAND TRACKING · UDP 8766", 10, MUTED, true));
        screen.addView(heading);
        FrameLayout cameraStage = new FrameLayout(this);
        preview = new PreviewView(this);
        preview.setImplementationMode(PreviewView.ImplementationMode.COMPATIBLE);
        preview.setScaleType(PreviewView.ScaleType.FILL_CENTER);
        cameraStage.addView(preview, new FrameLayout.LayoutParams(-1, -1));
        overlay = new HandOverlay(this);
        cameraStage.addView(overlay, new FrameLayout.LayoutParams(-1, -1));
        TextView cameraPill = text("LIVE CAMERA · 21 JOINTS / HAND", 10, WHITE, true);
        cameraPill.setPadding(dip(14), dip(8), dip(14), dip(8));
        cameraPill.setBackground(rounded(0xD0101923, EDGE, 12));
        FrameLayout.LayoutParams badge = new FrameLayout.LayoutParams(-2, -2, Gravity.TOP|Gravity.LEFT);
        badge.setMargins(dip(12), dip(12), 0, 0);
        cameraStage.addView(cameraPill, badge);
        screen.addView(cameraStage, new LinearLayout.LayoutParams(-1, 0, 1));

        LinearLayout controls = new LinearLayout(this);
        controls.setOrientation(LinearLayout.VERTICAL);
        controls.setPadding(dip(17), dip(13), dip(17), dip(18));
        controls.setBackground(rounded(PANEL, 0, 18));
        screen.addView(controls);
        LinearLayout title = new LinearLayout(this);
        title.setGravity(Gravity.CENTER_VERTICAL);
        TextView t = text("01  ·  PAIR WITH PC", 11, MUTED, true);
        title.addView(t, new LinearLayout.LayoutParams(0, -2, 1));
        flipButton = button("↻  FLIP", false);
        flipButton.setOnClickListener(v -> {front=!front; startCamera();});
        title.addView(flipButton);
        controls.addView(title);
        LinearLayout fields = new LinearLayout(this);
        fields.setOrientation(LinearLayout.HORIZONTAL);
        fields.setPadding(0, dip(12), 0, dip(11));
        LinearLayout ipcol = new LinearLayout(this); ipcol.setOrientation(LinearLayout.VERTICAL);
        ipcol.addView(text("PC WI-FI IP", 9, MUTED, true));
        ipInput = input("192.168.1.10", getPreferences(0).getString("ip", ""));
        ipcol.addView(ipInput);
        fields.addView(ipcol, new LinearLayout.LayoutParams(0, -2, 1.7f));
        LinearLayout codecol = new LinearLayout(this); codecol.setOrientation(LinearLayout.VERTICAL);
        codecol.setPadding(dip(9),0,0,0);
        codecol.addView(text("PAIR CODE", 9, MUTED, true));
        codeInput = input("123456", "");
        codeInput.setInputType(InputType.TYPE_CLASS_NUMBER);
        codecol.addView(codeInput);
        fields.addView(codecol, new LinearLayout.LayoutParams(0, -2, 1));
        controls.addView(fields);
        connectButton = button("CONNECT  →", true);
        connectButton.setOnClickListener(v -> onConnectClicked());
        controls.addView(connectButton, new LinearLayout.LayoutParams(-1, dip(52)));
        state = text("INITIALIZING TRACKER...", 11, MUTED, true);
        state.setPadding(0, dip(13), 0, dip(1));
        controls.addView(state);
        stats = text("Frames: —   ·   Hands: —   ·   Video stays on phone", 10, MUTED, false);
        controls.addView(stats);
    }

    private void status(String msg, boolean ok) {
        if (state != null) {state.setText(msg); state.setTextColor(ok ? MINT : MUTED);}
    }

    private void startCamera() {
        if (landmarker == null) return;
        ListenableFuture<ProcessCameraProvider> f = ProcessCameraProvider.getInstance(this);
        f.addListener(() -> {
            try {
                provider = f.get();
                provider.unbindAll();
                Preview p = new Preview.Builder().build();
                p.setSurfaceProvider(preview.getSurfaceProvider());
                ImageAnalysis analysis = new ImageAnalysis.Builder()
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setTargetResolution(new android.util.Size(640, 480))
                    .build();
                analysis.setAnalyzer(cameraWorker, this::analyze);
                CameraSelector selector = front ? CameraSelector.DEFAULT_FRONT_CAMERA : CameraSelector.DEFAULT_BACK_CAMERA;
                provider.bindToLifecycle(this, selector, p, analysis);
                status(sending ? "CONNECTING TO PC..." : "CAMERA READY · ENTER PC ADDRESS", true);
            } catch (Exception ex) {
                status("CAMERA ERROR: " + ex.getMessage(), false);
            }
        }, ContextCompat.getMainExecutor(this));
    }

    private void analyze(@NonNull ImageProxy image) {
        try {
            if (landmarker == null) return;
            Bitmap bitmap = image.toBitmap();
            int degrees = image.getImageInfo().getRotationDegrees();
            if (degrees != 0) {
                Matrix matrix = new Matrix(); matrix.postRotate(degrees);
                bitmap = Bitmap.createBitmap(bitmap, 0, 0, bitmap.getWidth(), bitmap.getHeight(), matrix, true);
            }
            int rw = bitmap.getWidth(), rh = bitmap.getHeight();
            // Image lifetime is safe: BitmapImageBuilder references an independent Bitmap.
            inputWidth = rw; inputHeight = rh;
            MPImage mpImage = new BitmapImageBuilder(bitmap).build();
            landmarker.detectAsync(mpImage, SystemClock.uptimeMillis());
        } catch (Exception ex) {
            android.util.Log.w("HandLink", "Frame processing skipped", ex);
        } finally {
            image.close();
        }
    }
    private volatile int inputWidth = 480, inputHeight = 640;

    private void onLandmarks(HandLandmarkerResult result) {
        long now = SystemClock.elapsedRealtime();
        frames++;
        List<float[][]> next = new ArrayList<>();
        List<List<NormalizedLandmark>> detected = result.landmarks();
        for (int hand = 0; hand < detected.size(); hand++) {
            List<NormalizedLandmark> src = detected.get(hand);
            if (src.size() != 21) continue;
            float[][] points = new float[21][3];
            for (int j=0;j<21;j++) {
                points[j][0] = src.get(j).x();
                points[j][1] = src.get(j).y();
                points[j][2] = src.get(j).z();
            }
            next.add(points);
            if (sending && udp != null && pcAddress != null) {
                String label = hand == 0 ? "Right" : "Left";
                try {
                    if (result.handedness().size() > hand && !result.handedness().get(hand).isEmpty())
                        label = result.handedness().get(hand).get(0).categoryName();
                } catch (Exception ignored) {}
                if (!label.equals("Left") && !label.equals("Right")) label = "Right";
                sendPacket(points, label);
            }
        }
        if (now - lastPreviewUpdate > 35) {
            lastPreviewUpdate = now;
            int iw = inputWidth, ih = inputHeight;
            runOnUiThread(() -> overlay.setHands(next, iw, ih, front));
        }
        if (now - lastFpsUpdate >= 1000) {
            final int n = frames;
            frames = 0;
            lastFpsUpdate = now;
            final int numHands = detected.size();
            runOnUiThread(() -> {
                stats.setText("Tracking: " + n + " fps   ·   Hands: " + numHands +
                    "   ·   Video stays on phone");
                if (sending && now - lastAck > 2500) {
                    paired = false;
                    status("NO PC ACK · CHECK IP, CODE & FIREWALL", false);
                }
            });
        }
    }

    private static double round4(float v) {return Math.round(v*10000.0)/10000.0;}
    private void sendPacket(float[][] points, String side) {
        DatagramSocket s = udp; InetAddress dest = pcAddress;
        if (s == null || dest == null) return;
        try {
            JSONObject body = new JSONObject();
            body.put("v", 1); body.put("kind", "hand");
            body.put("code", pairCode); body.put("seq", seq++ % 2147483646);
            body.put("hand", side);
            JSONArray arr = new JSONArray();
            for (float[] point : points) {
                double x = front ? 1.0-point[0] : point[0];
                arr.put(new JSONArray().put(round4((float)Math.max(0, Math.min(1, x))))
                    .put(round4(Math.max(0, Math.min(1, point[1]))))
                    .put(round4(Math.max(-2, Math.min(2, point[2])))));
            }
            body.put("points", arr);
            float dx = points[4][0] - points[8][0];
            float dy = points[4][1] - points[8][1];
            float baseX = points[0][0] - points[9][0];
            float baseY = points[0][1] - points[9][1];
            double palm = Math.max(.015, Math.hypot(baseX, baseY));
            double pinch = Math.max(0, Math.min(1, 1 - Math.hypot(dx, dy) / (palm*.85)));
            body.put("pinch", Math.round(pinch*1000)/1000.0);
            byte[] bytes = body.toString().getBytes(StandardCharsets.UTF_8);
            // One datagram per hand avoids oversized packets / IP fragmentation.
            if (bytes.length <= 1200) s.send(new DatagramPacket(bytes, bytes.length, dest, 8766));
        } catch (Exception ex) {
            android.util.Log.w("HandLink", "UDP send skipped", ex);
        }
    }

    private void onConnectClicked() {
        if (sending) { disconnect(); return; }
        String ip = ipInput.getText().toString().trim();
        String code = codeInput.getText().toString().trim();
        if (ip.isEmpty() || !code.matches("\\d{6}")) {
            status("ENTER PC IP AND 6-DIGIT PAIR CODE", false);
            return;
        }
        getPreferences(0).edit().putString("ip", ip).apply();
        pairCode = code;
        sending = true; paired = false; lastAck = SystemClock.elapsedRealtime();
        connectButton.setText("DISCONNECT  ■");
        status("CONNECTING · WAIT FOR PC ACK...", false);
        networkWorker.execute(() -> {
            try {
                InetAddress target = InetAddress.getByName(ip);
                DatagramSocket socket = new DatagramSocket();
                socket.setSoTimeout(900);
                udp = socket; pcAddress = target;
                byte[] buffer = new byte[1024];
                long lastHello = 0;
                while (sending && !socket.isClosed()) {
                    if (SystemClock.elapsedRealtime() - lastHello > 850) {
                        byte[] hello = ("{\"v\":1,\"kind\":\"hello\",\"code\":\"" + pairCode + "\"}")
                            .getBytes(StandardCharsets.UTF_8);
                        socket.send(new DatagramPacket(hello, hello.length, target, 8766));
                        lastHello = SystemClock.elapsedRealtime();
                    }
                    try {
                        DatagramPacket reply = new DatagramPacket(buffer, buffer.length);
                        socket.receive(reply);
                        JSONObject response = new JSONObject(new String(reply.getData(), reply.getOffset(),
                            reply.getLength(), StandardCharsets.UTF_8));
                        if (response.optInt("v") == 1 && response.optString("kind").equals("ack") &&
                            response.optString("code").equals(pairCode) && reply.getAddress().equals(target)) {
                            paired = true;
                            lastAck = SystemClock.elapsedRealtime();
                            runOnUiThread(() -> status("● CONNECTED · STREAMING HANDS", true));
                        }
                    } catch (java.net.SocketTimeoutException ignored) {}
                }
            } catch (Exception ex) {
                runOnUiThread(() -> status("NETWORK ERROR: " + ex.getMessage(), false));
            } finally {
                DatagramSocket socket = udp;
                if (socket != null) socket.close();
                udp = null;
            }
        });
    }

    private void disconnect() {
        sending = false; paired = false; pcAddress = null;
        DatagramSocket s = udp;
        if (s != null) s.close();
        connectButton.setText("CONNECT  →");
        status("DISCONNECTED · CAMERA STILL RUNNING", false);
    }

    @Override public void onRequestPermissionsResult(int request, @NonNull String[] permissions,
                                                       @NonNull int[] results) {
        super.onRequestPermissionsResult(request, permissions, results);
        if (request == 100 && results.length > 0 && results[0] == PackageManager.PERMISSION_GRANTED)
            startCamera();
        else status("CAMERA PERMISSION REQUIRED · ENABLE IN SETTINGS", false);
    }

    @Override protected void onDestroy() {
        disconnect();
        if (provider != null) provider.unbindAll();
        cameraWorker.shutdown(); networkWorker.shutdownNow();
        if (landmarker != null) landmarker.close();
        super.onDestroy();
    }
}
