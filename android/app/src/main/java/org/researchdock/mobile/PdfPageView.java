package org.researchdock.mobile;
import android.content.Context;import android.graphics.*;import android.view.*;
/** One bounded page bitmap; gestures never parse document text. */
final class PdfPageView extends View {
 private Bitmap bitmap;private final Paint paint=new Paint(Paint.ANTI_ALIAS_FLAG|Paint.FILTER_BITMAP_FLAG);
 private float zoom=1,x=0,y=0,lastX,lastY;private boolean whole=false;private float[] pending;
 private final ScaleGestureDetector scale;private final GestureDetector taps;
 PdfPageView(Context c){super(c);setBackgroundColor(Color.rgb(230,227,226));setContentDescription("PDF 页面，双指缩放，拖动查看，双击放大");
  scale=new ScaleGestureDetector(c,new ScaleGestureDetector.SimpleOnScaleGestureListener(){public boolean onScale(ScaleGestureDetector d){changeZoom(zoom*d.getScaleFactor(),d.getFocusX(),d.getFocusY());return true;}});
  taps=new GestureDetector(c,new GestureDetector.SimpleOnGestureListener(){public boolean onDown(MotionEvent e){return true;}public boolean onDoubleTap(MotionEvent e){changeZoom(zoom>1.1f?1:2.5f,e.getX(),e.getY());return true;}});
 }
 private float base(){if(bitmap==null||getWidth()==0||getHeight()==0)return 1;return whole?Math.min((float)getWidth()/bitmap.getWidth(),(float)getHeight()/bitmap.getHeight()):(float)getWidth()/bitmap.getWidth();}
 private void constrain(){if(bitmap==null)return;float w=bitmap.getWidth()*base()*zoom,h=bitmap.getHeight()*base()*zoom;x=w<=getWidth()?(getWidth()-w)/2:Math.max(getWidth()-w,Math.min(0,x));y=h<=getHeight()?(getHeight()-h)/2:Math.max(getHeight()-h,Math.min(0,y));}
 void changeZoom(float value,float focusX,float focusY){float next=Math.max(1,Math.min(6,value)),factor=next/zoom;x=focusX-(focusX-x)*factor;y=focusY-(focusY-y)*factor;zoom=next;constrain();invalidate();}
 void fit(boolean entire){whole=entire;zoom=1;x=y=0;constrain();invalidate();}
 float[] position(){if(bitmap==null)return null;float s=base()*zoom;return new float[]{zoom,(getWidth()/2f-x)/(bitmap.getWidth()*s),(getHeight()/2f-y)/(bitmap.getHeight()*s),whole?1:0};}
 void page(Bitmap next,float[] restore){Bitmap old=bitmap;bitmap=next;pending=restore;zoom=1;whole=false;x=y=0;applyPending();constrain();invalidate();if(old!=null&&old!=next)old.recycle();}
 private void applyPending(){if(pending==null||getWidth()==0||getHeight()==0||bitmap==null)return;zoom=Math.max(1,Math.min(6,pending[0]));whole=pending[3]>0;float s=base()*zoom;x=getWidth()/2f-pending[1]*bitmap.getWidth()*s;y=getHeight()/2f-pending[2]*bitmap.getHeight()*s;pending=null;}
 @Override protected void onSizeChanged(int w,int h,int ow,int oh){super.onSizeChanged(w,h,ow,oh);applyPending();constrain();}
 @Override protected void onDraw(Canvas c){super.onDraw(c);if(bitmap!=null){c.save();c.translate(x,y);c.scale(base()*zoom,base()*zoom);c.drawBitmap(bitmap,0,0,paint);c.restore();}}
 @Override public boolean onTouchEvent(MotionEvent e){scale.onTouchEvent(e);taps.onTouchEvent(e);if(e.getActionMasked()==MotionEvent.ACTION_DOWN){lastX=e.getX();lastY=e.getY();}else if(e.getActionMasked()==MotionEvent.ACTION_MOVE){if(!scale.isInProgress()&&e.getPointerCount()==1){x+=e.getX()-lastX;y+=e.getY()-lastY;constrain();invalidate();}lastX=e.getX();lastY=e.getY();}else if(e.getActionMasked()==MotionEvent.ACTION_POINTER_UP){int index=e.getActionIndex()==0?1:0;if(index<e.getPointerCount()){lastX=e.getX(index);lastY=e.getY(index);}}else if(e.getActionMasked()==MotionEvent.ACTION_UP)performClick();return true;}
 @Override public boolean performClick(){super.performClick();return true;}
 void release(){page(null,null);}
}
