package org.researchdock.mobile;
import android.app.*;import android.content.*;import android.view.*;import android.widget.*;
import androidx.test.platform.app.InstrumentationRegistry;
import org.json.*;import org.junit.Test;import static org.junit.Assert.*;
public class WorkspacePresentationTest {
 private Object get(MainActivity a,String k)throws Exception{java.lang.reflect.Field f=MainActivity.class.getDeclaredField(k);f.setAccessible(true);return f.get(a);}
 private void set(MainActivity a,String k,Object v)throws Exception{java.lang.reflect.Field f=MainActivity.class.getDeclaredField(k);f.setAccessible(true);f.set(a,v);}
 private void call(MainActivity a,String k)throws Exception{java.lang.reflect.Method m=MainActivity.class.getDeclaredMethod(k);m.setAccessible(true);m.invoke(a);}
 private void article(MainActivity a,JSONObject d)throws Exception{java.lang.reflect.Method m=MainActivity.class.getDeclaredMethod("showArticle",JSONObject.class);m.setAccessible(true);m.invoke(a,d);}
 private String text(View v){StringBuilder b=new StringBuilder();if(v instanceof TextView)b.append(((TextView)v).getText()).append('\n');if(v instanceof ViewGroup)for(int i=0;i<((ViewGroup)v).getChildCount();i++)b.append(text(((ViewGroup)v).getChildAt(i)));return b.toString();}
 private Button button(View v,String label){if(v instanceof Button&&((Button)v).getText().toString().equals(label))return (Button)v;if(v instanceof ViewGroup)for(int i=0;i<((ViewGroup)v).getChildCount();i++){Button b=button(((ViewGroup)v).getChildAt(i),label);if(b!=null)return b;}return null;}
 @Test public void workspaceAndExistingAnalysisPreserveTheirMeaning()throws Exception{
  if(!"true".equals(InstrumentationRegistry.getArguments().getString("navigation_test")))return;
  Instrumentation inst=InstrumentationRegistry.getInstrumentation();MainActivity a=(MainActivity)inst.startActivitySync(new Intent(inst.getTargetContext(),MainActivity.class).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK));
  for(int n=0;n<150;n++){if(!(Boolean)get(a,"syncing"))break;Thread.sleep(100);}assertFalse((Boolean)get(a,"syncing"));
  SharedPreferences prefs=a.getSharedPreferences("reader",Context.MODE_PRIVATE);String previous=prefs.getString("last_article","");boolean had=prefs.contains("follow:合成关注公司"),old=prefs.getBoolean("follow:合成关注公司",false);
  String today=java.time.LocalDate.now(java.time.ZoneId.of("Asia/Shanghai")).toString();JSONArray docs=new JSONArray();for(int n=0;n<3;n++){JSONObject d=new JSONObject().put("document_id","workspace-fixture-"+n).put("revision",1).put("title","合成材料"+n).put("summary","测试样例，不是真实研报").put("first_imported_at",(n==2?"2020-01-01":today)+"T09:00:00+08:00").put("published_at",n==0?"2020-01-01T09:00:00+08:00":today+"T09:00:00+08:00").put("companies",new JSONArray().put(n==1?"其他合成公司":"合成关注公司"));docs.put(d);}
  JSONObject article=new JSONObject().put("document_id","workspace-analysis-fixture").put("revision",1).put("analysis_revision",1).put("title","本地工作台验证，非真实研报").put("summary","既有摘要示例").put("key_points",new JSONArray().put("观点一").put("观点二").put("观点三").put("观点四（展开后）")).put("risks",new JSONArray().put("风险示例，不作判断")).put("body","# 原文证据\n完整的合成原文，不调用模型。");
  try{
   inst.runOnMainSync(()->{try{prefs.edit().putBoolean("follow:合成关注公司",true).apply();set(a,"docs",docs);set(a,"tab","动态");set(a,"feedMode","全部");call(a,"render");View root=(View)get(a,"root");String value=text(root);assertTrue(value.contains("今日收录 2"));assertTrue(value.contains("关注未读 2"));assertTrue(value.contains("关注公司 · 未读研究"));assertNotNull(button(root,"今日"));button(root,"今日").performClick();value=text((View)get(a,"root"));assertTrue(value.contains("合成材料0"));assertTrue(value.contains("合成材料1"));assertFalse(value.contains("合成材料2"));article(a,article);}catch(Exception e){throw new RuntimeException(e);}});inst.waitForIdleSync();Thread.sleep(150);
   inst.runOnMainSync(()->{try{View root=(View)get(a,"root");String value=text(root);assertTrue(value.contains("关键观点"));assertTrue(value.contains("风险提示"));assertTrue(value.contains("观点一"));assertFalse(value.contains("观点四（展开后）"));button(root,"展开其余 1 条").performClick();assertTrue(text(root).contains("观点四（展开后）"));JSONObject stale=new JSONObject(article.toString()).put("revision",2);article(a,stale);value=text((View)get(a,"root"));assertFalse(value.contains("观点一"));assertFalse(value.contains("风险示例，不作判断"));call(a,"returnToList");}catch(Exception e){throw new RuntimeException(e);}});
  }finally{inst.runOnMainSync(()->{SharedPreferences.Editor edit=prefs.edit().putString("last_article",previous).remove("progress:workspace-analysis-fixture:r1").remove("progress:workspace-analysis-fixture:r2");if(had)edit.putBoolean("follow:合成关注公司",old);else edit.remove("follow:合成关注公司");edit.apply();a.finish();});}
 }
}
