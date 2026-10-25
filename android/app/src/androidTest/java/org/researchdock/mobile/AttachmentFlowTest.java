package org.researchdock.mobile;
import android.app.*;
import android.content.*;
import android.database.Cursor;
import android.net.Uri;
import android.os.*;
import android.widget.*;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import java.io.*;
import java.util.*;
import static org.junit.Assert.*;
public class AttachmentFlowTest {
 private Object get(MainActivity a,String key)throws Exception{java.lang.reflect.Field f=MainActivity.class.getDeclaredField(key);f.setAccessible(true);return f.get(a);}
 private Object call(MainActivity a,String key,Class<?>[] types,Object... args)throws Exception{java.lang.reflect.Method m=MainActivity.class.getDeclaredMethod(key,types);m.setAccessible(true);return m.invoke(a,args);}
 @Test public void attachmentProviderIsReadOnlyAndPathBounded()throws Exception{
  Context c=InstrumentationRegistry.getInstrumentation().getTargetContext();String hash=new String(new char[64]).replace('\0','f');File f=new File(c.getFilesDir(),"asset-"+hash);assertFalse("Fixture must not replace real cache",f.exists());try{
   try(FileOutputStream out=new FileOutputStream(f)){out.write("ID3 synthetic fixture".getBytes());}
   Uri u=Uri.parse("content://org.researchdock.mobile.attachments/asset/"+hash+"/sample.mp3");assertEquals("audio/mpeg",c.getContentResolver().getType(u));try(Cursor cursor=c.getContentResolver().query(u,null,null,null,null)){assertNotNull(cursor);assertTrue(cursor.moveToFirst());assertEquals("sample.mp3",cursor.getString(0));}
   try(ParcelFileDescriptor fd=c.getContentResolver().openFileDescriptor(u,"r")){assertNotNull(fd);}
   try{c.getContentResolver().openFileDescriptor(u,"w");fail("Must deny writes");}catch(FileNotFoundException expected){}
   try{c.getContentResolver().openFileDescriptor(Uri.parse("content://org.researchdock.mobile.attachments/asset/not-a-hash/sample.mp3"),"r");fail("Must deny arbitrary paths");}catch(FileNotFoundException expected){}
   android.content.pm.ProviderInfo p=c.getPackageManager().resolveContentProvider("org.researchdock.mobile.attachments",0);assertNotNull(p);assertFalse(p.exported);assertTrue(p.grantUriPermissions);
  }finally{f.delete();}
 }
 @Test public void attachmentNamesAreSearchableWithoutTreatingFormatsAsTickers()throws Exception{JSONObject d=new JSONObject();d.put("title","汇总资料");d.put("attachments",new JSONArray().put(new JSONObject().put("name","示例行业原始表.xlsx")));assertFalse(LibraryViews.isCodeQuery("XLSX"));assertTrue(LibraryViews.matches(d,"原始表","",0,"全部",false,false,0,java.time.LocalDate.now()));assertFalse(LibraryViews.matches(d,"不存在文件","",0,"全部",false,false,0,java.time.LocalDate.now()));}
 @Test public void liveOriginalDeliveryProbe()throws Exception{
  String wanted=InstrumentationRegistry.getArguments().getString("attachment_probe");if(wanted==null)return;
  Instrumentation inst=InstrumentationRegistry.getInstrumentation();MainActivity a=(MainActivity)inst.startActivitySync(new Intent(inst.getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
  JSONObject report=new JSONObject();try{
   // Fetch catalog using the configured private reader credentials; never log credentials, filenames or bodies.
   JSONObject chosen=null,item=null;int offset=0;
   outer:while(true){JSONObject page=(JSONObject)call(a,"request",new Class<?>[]{String.class,String.class,JSONObject.class},"GET","/v1/documents?limit=100&offset="+offset,null);JSONArray docs=page.getJSONArray("documents");for(int n=0;n<docs.length();n++){JSONObject d=docs.getJSONObject(n);JSONArray list=d.optJSONArray("attachments");if(list!=null)for(int j=0;j<list.length();j++){JSONObject x=list.getJSONObject(j);if(x.optString("type").equals(wanted)&&x.optLong("size")<4000000&&!x.optString("status").equals("unavailable")){chosen=d;item=x;break outer;}}}offset+=docs.length();if(!page.optBoolean("has_more"))break;}
   assertNotNull("Requested attachment type must be in full inventory",item);String id=chosen.getString("document_id"),key=item.getString("id");long start=System.currentTimeMillis();
   call(a,"request",new Class<?>[]{String.class,String.class,JSONObject.class},"POST","/v1/documents/"+id+"/attachments/"+key+"/prepare",new JSONObject());JSONObject full=null;
   for(int attempt=0;attempt<75;attempt++){full=(JSONObject)call(a,"request",new Class<?>[]{String.class,String.class,JSONObject.class},"GET","/v1/documents/"+id,null);JSONArray items=full.getJSONArray("attachments");for(int j=0;j<items.length();j++)if(items.getJSONObject(j).getString("id").equals(key))item=items.getJSONObject(j);if(item.optString("status").equals("ready"))break;assertFalse("Mac failed to prepare original",item.optString("status").equals("failed")&&full.optLong("sequence")>chosen.optLong("sequence"));Thread.sleep(3000);}
   assertEquals("ready",item.getString("status"));File file=(File)call(a,"asset",new Class<?>[]{String.class},item.getString("asset_id"));assertTrue(file.length()>0);report.put("type",wanted);report.put("bytes",file.length());report.put("ready",true);report.put("elapsed_ms",System.currentTimeMillis()-start);
   final JSONObject display=full;inst.runOnMainSync(()->{try{call(a,"showArticle",new Class<?>[]{JSONObject.class},display);}catch(Exception e){throw new RuntimeException(e);}});Thread.sleep(500);inst.waitForIdleSync();report.put("reader_opened",true);
   try(FileOutputStream out=new FileOutputStream(new File(a.getFilesDir(),"attachment-probe-"+wanted+".json"))){out.write(report.toString(2).getBytes());}Bundle result=new Bundle();result.putString("stream",report.toString()+"\n");inst.sendStatus(0,result);
  }finally{inst.runOnMainSync(()->{a.onBackPressed();a.finish();});}
 }
}
