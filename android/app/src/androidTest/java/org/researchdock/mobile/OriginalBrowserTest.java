package org.researchdock.mobile;
import android.app.*;
import android.content.*;
import android.widget.*;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;
import org.junit.Test;
import static org.junit.Assert.*;
public class OriginalBrowserTest {
 private Object get(MainActivity a,String k)throws Exception{java.lang.reflect.Field f=MainActivity.class.getDeclaredField(k);f.setAccessible(true);return f.get(a);}
 private void set(MainActivity a,String k,Object v)throws Exception{java.lang.reflect.Field f=MainActivity.class.getDeclaredField(k);f.setAccessible(true);f.set(a,v);}
 private void call(MainActivity a,String k)throws Exception{java.lang.reflect.Method m=MainActivity.class.getDeclaredMethod(k);m.setAccessible(true);m.invoke(a);}
 @Test public void selectedOriginalFocusAndBackKeepFileFiltersAndPosition()throws Exception{
  if(!"true".equals(InstrumentationRegistry.getArguments().getString("navigation_test")))return;
  Instrumentation inst=InstrumentationRegistry.getInstrumentation();MainActivity a=(MainActivity)inst.startActivitySync(new Intent(inst.getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));SharedPreferences prefs=a.getSharedPreferences("reader",Context.MODE_PRIVATE);String previous=prefs.getString("last_article","");
  String key=new String(new char[64]).replace('\0','a');JSONObject d=new JSONObject().put("document_id","original-browser-regression").put("revision",1).put("title","临时原件导航测试");StringBuilder body=new StringBuilder("# 合成样例\n");for(int i=0;i<100;i++)body.append("第").append(i).append("段：用于验证附件定位与返回，不写入资料库。\n\n");d.put("body",body.toString()).put("attachments",new JSONArray().put(new JSONObject().put("id",key).put("name","合成待获取.mp3").put("type","audio").put("status","missing").put("asset_id","").put("message","测试样例，不发起请求")));
  Object[] list={null};int[] y={0};try{
   inst.runOnMainSync(()->{try{set(a,"tab","原件");set(a,"originalType","audio");set(a,"originalState","missing");set(a,"listLimit",60);call(a,"render");}catch(Exception e){throw new RuntimeException(e);}});inst.waitForIdleSync();
   inst.runOnMainSync(()->{try{ScrollView scroll=(ScrollView)get(a,"scroll");scroll.scrollTo(0,1200);y[0]=scroll.getScrollY();assertTrue(y[0]>500);list[0]=get(a,"content");java.lang.reflect.Method show=MainActivity.class.getDeclaredMethod("showArticle",JSONObject.class,String.class);show.setAccessible(true);show.invoke(a,d,key);}catch(Exception e){throw new RuntimeException(e);}});
   for(int i=0;i<100;i++){boolean[] pending={false};inst.runOnMainSync(()->{try{pending[0]=(Boolean)get(a,"articleRenderPending");}catch(Exception e){throw new RuntimeException(e);}});if(!pending[0])break;Thread.sleep(30);}inst.waitForIdleSync();Thread.sleep(150);
   inst.runOnMainSync(()->{try{assertFalse((Boolean)get(a,"articleRenderPending"));assertTrue(((ScrollView)get(a,"scroll")).getScrollY()>1000);assertNotNull(((LinearLayout)get(a,"attachmentBoxForArticle")).findViewWithTag("attachment:"+key));call(a,"returnToList");}catch(Exception e){throw new RuntimeException(e);}});inst.waitForIdleSync();Thread.sleep(100);
   inst.runOnMainSync(()->{try{assertSame(list[0],get(a,"content"));assertEquals(y[0],((ScrollView)get(a,"scroll")).getScrollY(),3);assertEquals("audio",get(a,"originalType"));assertEquals("missing",get(a,"originalState"));assertEquals(60,get(a,"listLimit"));}catch(Exception e){throw new RuntimeException(e);}});
  }finally{inst.runOnMainSync(()->{prefs.edit().putString("last_article",previous).remove("progress:original-browser-regression:r1").apply();a.finish();});}
 }
}
