package org.researchdock.mobile;
import android.app.*;import android.content.*;import android.graphics.*;import android.graphics.pdf.PdfDocument;import android.widget.*;
import androidx.test.platform.app.InstrumentationRegistry;
import org.junit.Test;import static org.junit.Assert.*;
public class PdfReaderTest {
 private Object get(Object a,String k)throws Exception{java.lang.reflect.Field f=a.getClass().getDeclaredField(k);f.setAccessible(true);return f.get(a);}
 private void ready(PdfReaderActivity a)throws Exception{for(int n=0;n<200;n++){if(!(Boolean)get(a,"loading"))break;Thread.sleep(50);}assertFalse((Boolean)get(a,"loading"));assertEquals(3,get(a,"total"));}
 @Test public void pageNavigationZoomResumeAndBackKeepTheOriginalArticle()throws Exception{
  if(!"true".equals(InstrumentationRegistry.getArguments().getString("navigation_test")))return;
  Instrumentation inst=InstrumentationRegistry.getInstrumentation();Context c=inst.getTargetContext();String id="eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee";java.io.File file=new java.io.File(c.getFilesDir(),"asset-"+id);assertFalse(file.exists());
  try(PdfDocument doc=new PdfDocument()){Paint paint=new Paint();paint.setTextSize(18);for(int n=0;n<3;n++){PdfDocument.Page p=doc.startPage(new PdfDocument.PageInfo.Builder(595,842,n).create());p.getCanvas().drawText("Synthetic PDF test page "+(n+1),40,60,paint);for(int line=0;line<18;line++)p.getCanvas().drawText("Local test content, no report data or model calls.",40,110+line*30,paint);doc.finishPage(p);}try(java.io.FileOutputStream out=new java.io.FileOutputStream(file)){doc.writeTo(out);}}
  MainActivity main=(MainActivity)inst.startActivitySync(new Intent(c,MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));for(int n=0;n<300&&(Boolean)get(main,"syncing");n++)Thread.sleep(100);
  SharedPreferences prefs=c.getSharedPreferences("reader",Context.MODE_PRIVATE);String previous=prefs.getString("last_article","");PdfReaderActivity pdf=null;final Object[] article={null};
  try{
   inst.runOnMainSync(()->{try{org.json.JSONObject d=new org.json.JSONObject().put("document_id","pdf-reader-source-test").put("revision",1).put("title","Synthetic PDF source").put("body","# Synthetic source\nReturn to this article after PDF reading.");java.lang.reflect.Method m=MainActivity.class.getDeclaredMethod("showArticle",org.json.JSONObject.class);m.setAccessible(true);m.invoke(main,d);article[0]=get(main,"content");}catch(Exception e){throw new RuntimeException(e);}});
   Intent intent=new Intent(c,PdfReaderActivity.class).putExtra("asset_id",id).putExtra("name","Synthetic test.pdf").addFlags(Intent.FLAG_ACTIVITY_NEW_TASK);
   pdf=(PdfReaderActivity)inst.startActivitySync(intent);ready(pdf);PdfReaderActivity first=pdf;
   inst.runOnMainSync(()->{try{assertEquals(0,get(first,"page"));assertFalse(((Button)get(first,"previous")).isEnabled());PdfPageView image=(PdfPageView)get(first,"image");image.changeZoom(2.5f,image.getWidth()/2f,image.getHeight()/2f);assertEquals(2.5f,image.position()[0],.01f);((Button)get(first,"next")).performClick();}catch(Exception e){throw new RuntimeException(e);}});ready(pdf);assertEquals(1,get(pdf,"page"));
   java.lang.reflect.Method load=PdfReaderActivity.class.getDeclaredMethod("load",int.class,float[].class);load.setAccessible(true);inst.runOnMainSync(()->{try{load.invoke(first,99,null);}catch(Exception e){throw new RuntimeException(e);}});ready(pdf);assertEquals(2,get(pdf,"page"));assertFalse(((Button)get(pdf,"next")).isEnabled());inst.runOnMainSync(first::finish);inst.waitForIdleSync();
   assertSame(article[0],get(main,"content"));assertTrue((Boolean)get(main,"reading"));
   pdf=(PdfReaderActivity)inst.startActivitySync(intent);ready(pdf);assertEquals(2,get(pdf,"page"));PdfReaderActivity second=pdf;inst.runOnMainSync(()->{try{PdfPageView image=(PdfPageView)get(second,"image");image.fit(true);assertEquals(1,image.position()[3],.01f);image.fit(false);assertEquals(0,image.position()[3],.01f);}catch(Exception e){throw new RuntimeException(e);}});
  }finally{if(pdf!=null){PdfReaderActivity end=pdf;inst.runOnMainSync(end::finish);}inst.runOnMainSync(()->{SharedPreferences.Editor edit=prefs.edit().putString("last_article",previous).remove("progress:pdf-reader-source-test:r1");for(String k:prefs.getAll().keySet())if(k.startsWith("pdf:"+id+":"))edit.remove(k);edit.commit();main.finish();});file.delete();}
 }
}
