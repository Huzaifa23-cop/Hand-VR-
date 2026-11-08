package dev.handlink.mobile;

import android.content.Context;
import android.graphics.Canvas;
import android.graphics.Paint;
import android.view.View;
import java.util.ArrayList;
import java.util.List;

/** Lightweight MediaPipe 21-landmark wireframe on the camera preview. */
public final class HandOverlay extends View {
    private static final int[][] BONES = {
        {0,1},{1,2},{2,3},{3,4}, {0,5},{5,6},{6,7},{7,8},
        {0,9},{9,10},{10,11},{11,12}, {0,13},{13,14},{14,15},{15,16},
        {0,17},{17,18},{18,19},{19,20}, {5,9},{9,13},{13,17}
    };
    private final Paint p = new Paint(Paint.ANTI_ALIAS_FLAG);
    private List<float[][]> hands = new ArrayList<>();
    private int imageWidth = 480;
    private int imageHeight = 640;
    private boolean mirror = true;

    public HandOverlay(Context context) { super(context); setWillNotDraw(false); }

    /** Coordinates in rotated camera image space, before preview mirroring. */
    public void setHands(List<float[][]> next, int width, int height, boolean isFront) {
        hands = next;
        imageWidth = Math.max(1, width);
        imageHeight = Math.max(1, height);
        mirror = isFront;
        invalidate();
    }

    @Override protected void onDraw(Canvas c) {
        super.onDraw(c);
        float scale = Math.max(getWidth()/(float)imageWidth, getHeight()/(float)imageHeight);
        float drawWidth = imageWidth * scale;
        float drawHeight = imageHeight * scale;
        float dx = (drawWidth-getWidth())/2f;
        float dy = (drawHeight-getHeight())/2f;
        for (int hand=0; hand<hands.size(); hand++) {
            float[][] pts = hands.get(hand);
            if (pts.length < 21) continue;
            int color = hand == 0 ? 0xFF8CF7CB : 0xFF75BFFF;
            p.setStyle(Paint.Style.STROKE); p.setColor(0xC5081520); p.setStrokeWidth(10f);
            for (int[] bone: BONES) c.drawLine(px(pts[bone[0]][0],drawWidth,dx),
                pts[bone[0]][1]*drawHeight-dy, px(pts[bone[1]][0],drawWidth,dx),
                pts[bone[1]][1]*drawHeight-dy, p);
            p.setColor(color); p.setStrokeWidth(3.8f);
            for (int[] bone: BONES) c.drawLine(px(pts[bone[0]][0],drawWidth,dx),
                pts[bone[0]][1]*drawHeight-dy, px(pts[bone[1]][0],drawWidth,dx),
                pts[bone[1]][1]*drawHeight-dy, p);
            p.setStyle(Paint.Style.FILL); p.setColor(color);
            for (int i=0;i<21;i++) c.drawCircle(px(pts[i][0],drawWidth,dx),
                pts[i][1]*drawHeight-dy, i==8?8:4.5f, p);
        }
    }
    private float px(float x,float width,float offset) {
        return (mirror ? (1f-x) : x)*width-offset;
    }
}
