package org.researchdock.mobile;
import org.json.*;import org.junit.Test;import static org.junit.Assert.*;
import java.io.*;import java.nio.charset.StandardCharsets;import java.util.*;
import androidx.test.platform.app.InstrumentationRegistry;
public class CatalogSearchTest {
 private JSONObject d(String letter,int revision)throws Exception{return new JSONObject().put("document_id","doc_"+letter.repeat(26)).put("revision",revision).put("title","合成资料").put("body","😀只有正文出现的订单与现金流证据，不调用模型。").put("published_at","2026-10-26T09:00:00+08:00");}
 private JSONObject event(JSONObject d,long sequence)throws Exception{JSONObject meta=new JSONObject(d.toString());meta.remove("body");return new JSONObject().put("sequence",sequence).put("document_id",d.getString("document_id")).put("document",meta).put("deleted",false);}
 @Test public void fixedSnapshotThenDeltaPreservesUpdatesAndDeletes()throws Exception{
  ArrayList<String> paths=new ArrayList<>();int[] page={0};CatalogSync.Result snapshot=CatalogSync.fetch(path->{paths.add(path);return page[0]++==0?new JSONObject().put("epoch","synthetic").put("cursor",5).put("has_more",true).put("events",new JSONArray().put(event(d("A",1),2))):new JSONObject().put("epoch","synthetic").put("cursor",5).put("has_more",false).put("events",new JSONArray().put(event(d("B",1),4)));},new JSONArray(),0,false);
  assertEquals(2,snapshot.documents.length());assertTrue(paths.get(1).contains("until=5"));assertTrue(paths.get(1).contains("after_id=doc_A"));
  CatalogSync.Result delta=CatalogSync.fetch(path->new JSONObject().put("epoch","synthetic").put("cursor",8).put("has_more",false).put("events",new JSONArray().put(event(d("A",2),6)).put(new JSONObject().put("document_id",d("B",1).getString("document_id")).put("sequence",7).put("deleted",true).put("document",JSONObject.NULL)).put(event(d("C",1),8))),snapshot.documents,5,true);
  assertEquals(2,delta.documents.length());assertEquals(8,delta.cursor);assertEquals(2,delta.documents.getJSONObject(0).getInt("revision"));assertEquals(d("C",1).getString("document_id"),delta.documents.getJSONObject(1).getString("document_id"));
 }
 @Test public void invalidCursorBootstrapsAndBrokenPagesNeverReturnPartialCatalog()throws Exception{
  int[] calls={0};CatalogSync.Result result=CatalogSync.fetch(path->{if(calls[0]++==0)throw new MobileApi.Failure(409,"reset");return new JSONObject().put("epoch","synthetic").put("cursor",2).put("has_more",false).put("events",new JSONArray().put(event(d("C",1),2)));},new JSONArray().put(d("A",1)),999,true);assertTrue(result.snapshot);assertEquals(1,result.documents.length());assertEquals(d("C",1).getString("document_id"),result.documents.getJSONObject(0).getString("document_id"));
  try{CatalogSync.fetch(path->new JSONObject().put("epoch","synthetic").put("cursor",3).put("has_more",true).put("events",new JSONArray()),new JSONArray(),0,false);fail("empty pagination must fail");}catch(IOException expected){}
 }
 @Test public void offlineSearchFindsCachedBodyAndRejectsStaleOrDeletedDocuments()throws Exception{
  File root=new File(InstrumentationRegistry.getInstrumentation().getTargetContext().getCacheDir(),"search-fixture-"+UUID.randomUUID());assertTrue(root.mkdirs());JSONObject current=d("A",1),old=d("B",1),deleted=d("C",1);
  try{for(JSONObject row:new JSONObject[]{current,old,deleted})try(FileOutputStream out=new FileOutputStream(new File(root,row.getString("document_id")+".json"))){out.write(row.toString().getBytes(StandardCharsets.UTF_8));}
   JSONArray catalog=new JSONArray().put(current).put(d("B",2));JSONObject response=LocalSearch.search(root,catalog,"订单","","","",0);assertEquals(1,response.getJSONArray("results").length());JSONObject hit=response.getJSONArray("results").getJSONObject(0);assertEquals("body",hit.getString("match_field"));assertEquals("订单",hit.getString("snippet").substring(hit.getInt("match_start"),hit.getInt("match_end")));assertTrue(response.getInt("excluded_stale_caches")>0);assertEquals(0,response.getInt("model_requests"));
  }finally{for(File f:root.listFiles())assertTrue(f.delete());assertTrue(root.delete());}
 }
}
